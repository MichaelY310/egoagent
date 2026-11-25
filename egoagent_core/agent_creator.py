"""Module for creating AI agents from natural language descriptions."""

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IDENTITY_DIR = PROJECT_ROOT / "identity"

from config import CONFIG
from harness_blueprint import HarnessBlueprintService


def _replace_directory(source: Path, destination: Path, attempts: int = 5) -> None:
    """Atomically commit a staged directory, tolerating short Windows locks."""
    for attempt in range(max(1, attempts)):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (2 ** attempt))

TEMPLATES = {
    "code_review": {
        "traits": ["meticulous", "constructive", "thorough"],
        "tools": ["read", "search", "patch", "end_session"],
        "temperature": 0.3,
    },
    "coding": {
        "traits": ["efficient", "pragmatic", "test_driven"],
        "tools": ["read", "write", "patch", "search", "end_session"],
        "temperature": 0.5,
    },
    "research": {
        "traits": ["curious", "analytical", "systematic"],
        "tools": ["read", "search", "write", "end_session"],
        "temperature": 0.7,
    },
    "creative": {
        "traits": ["creative", "innovative", "open_minded"],
        "tools": ["read", "write", "search", "end_session"],
        "temperature": 0.9,
    },
    "devops": {
        "traits": ["systematic", "security_conscious", "efficient"],
        "tools": ["read", "write", "patch", "search", "end_session"],
        "temperature": 0.3,
    },
    "testing": {
        "traits": ["thorough", "systematic", "edge_case_aware"],
        "tools": ["read", "write", "patch", "search", "end_session"],
        "temperature": 0.4,
    },
}

_KEYWORD_MAP = {
    "code_review": ["review", "审查", "code review", "lint", "pr"],
    "coding": ["code", "编码", "实现", "开发", "implement", "develop"],
    "research": ["研究", "调研", "research", "分析", "analyze"],
    "creative": ["创意", "设计", "creative", "brainstorm", "idea"],
    "devops": ["部署", "运维", "docker", "devops", "deploy"],
    "testing": ["测试", "test", "qa"],
}

_TECH_KEYWORDS = {name: {} for name in ("react", "vue", "typescript", "node", "python", "rust", "go", "docker")}


def _match_template(description: str) -> str:
    """Match description to a template based on keywords."""
    desc_lower = description.lower()
    for template_name, keywords in _KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword in desc_lower:
                return template_name
    return "coding"


def _detect_tech_stack(description: str) -> List[str]:
    """Detect tech stack keywords from the description."""
    desc_lower = description.lower()
    detected = []
    for tech in _TECH_KEYWORDS:
        if tech in desc_lower:
            detected.append(tech)
    return detected


def _generate_name(description: str, template_name: str) -> str:
    """Generate an English-only name for the agent based on description and template."""
    # Extract English words first
    eng_words = re.findall(r"[a-zA-Z]+", description.lower())
    # Filter out stop words
    stop_words = {"a", "an", "the", "my", "me", "i", "to", "for", "and", "or", "is", "that", "this", "create", "make", "build", "help", "agent", "bot", "please", "want", "need"}
    eng_words = [w for w in eng_words if w not in stop_words and len(w) > 1]
    if eng_words:
        base = "_".join(eng_words[:3])
    else:
        # Fallback: use template name + timestamp suffix
        base = f"{template_name}_{int(time.time()) % 10000}"
    return f"{base}_agent"


def _build_system_prompt(template_name: str, traits: List[str], tech_stack: List[str]) -> str:
    """Build a system prompt from template info and tech stack."""
    trait_str = ", ".join(traits)
    prompt = f"You are a {template_name} agent with the following traits: {trait_str}.\n"
    prompt += "Your role is to assist with tasks in your domain of expertise.\n"
    if tech_stack:
        tech_str = ", ".join(tech_stack)
        prompt += f"You are proficient in the following technologies: {tech_str}.\n"
    prompt += "Always be helpful, accurate, and follow best practices."
    return prompt


def _normalize_agent_spec(spec: dict, description: str) -> dict:
    """Validate a model-authored Agent Spec without choosing its behavior."""

    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    role = str(spec.get("role") or "general agent").strip()[:200]
    traits = spec.get("traits", [])
    skills = spec.get("skills", [])
    knowledge_topics = spec.get("knowledge_topics", [])
    if not isinstance(traits, list) or not isinstance(skills, list) or not isinstance(knowledge_topics, list):
        raise ValueError("spec traits, skills and knowledge_topics must be arrays")

    def safe_values(values, label, limit):
        result = []
        for raw in values[:limit]:
            value = str(raw).strip()
            if not value:
                continue
            if label in {"skill", "knowledge"} and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,79}", value):
                raise ValueError(f"invalid {label} name: {value!r}")
            result.append(value[:120])
        return list(dict.fromkeys(result))

    prompt = str(spec.get("system_prompt") or "").strip()
    if not prompt:
        prompt = (
            f"You are a {role}. {description.strip()}\n"
            "Inspect evidence before acting. Use only installed capabilities and verify the final result."
        )
    try:
        temperature = float(spec.get("temperature", 0.4))
    except (TypeError, ValueError) as error:
        raise ValueError("spec temperature must be numeric") from error
    return {
        "role": role,
        "traits": safe_values(traits, "trait", 12) or ["deliberate", "evidence_driven"],
        "skills": safe_values(skills, "skill", 30),
        "knowledge_topics": safe_values(knowledge_topics, "knowledge", 30),
        "system_prompt": prompt[:20_000],
        "language": str(spec.get("language") or ("zh" if re.search(r"[\u4e00-\u9fff]", description) else "en"))[:20],
        "tone": str(spec.get("tone") or "professional and direct")[:200],
        "temperature": min(2.0, max(0.0, temperature)),
        "allow_self_evolution": bool(spec.get("allow_self_evolution", True)),
    }


def create_agent_from_description(description: str, name: str = None, spec: dict = None) -> Dict:
    """Create a real Identity + executable Skill pack + visual Harness.

    This path is deterministic on purpose: even a weak model only has to state
    the role.  It never has to hand-write Python or raw DAG JSON.
    """
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    if spec is None:
        # Legacy convenience path used by the old REST form. New DAGs should
        # have an ordinary Model author a structured spec and pass it here.
        template_name = _match_template(description)
        template = TEMPLATES[template_name]
        tech_stack = _detect_tech_stack(description)
        normalized = {
            "role": f"{template_name.replace('_', ' ')} agent",
            "traits": list(template["traits"]),
            "skills": list(template["tools"]),
            "knowledge_topics": tech_stack,
            "system_prompt": _build_system_prompt(template_name, list(template["traits"]), tech_stack),
            "language": "zh" if re.search(r"[\u4e00-\u9fff]", description) else "en",
            "tone": "professional and direct",
            "temperature": template["temperature"],
            "allow_self_evolution": True,
        }
    else:
        template_name = "custom"
        normalized = _normalize_agent_spec(spec, description)

    if name is None:
        name = str((spec or {}).get("name") or "") or _generate_name(description, template_name)

    name = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "").strip("_")
    if not name or not re.match(r"^[A-Za-z_]", name):
        name = _generate_name(description, template_name)

    # Handle name conflicts without overwriting user data.
    agent_dir = IDENTITY_DIR / name
    harness_name = f"{name}_harness"
    if agent_dir.exists() or (PROJECT_ROOT / "harness" / harness_name).exists():
        suffix = int(time.time()) % 10000
        name = f"{name}_{suffix}"
        agent_dir = IDENTITY_DIR / name
        harness_name = f"{name}_harness"

    # These names map to real, copied Skill directories.  The old creator only
    # wrote names into tools.json, a file the runtime never reads.
    tools = normalized["skills"]
    traits = normalized["traits"]
    tech_stack = normalized["knowledge_topics"]
    system_prompt = normalized["system_prompt"]
    default_llm = {}
    try:
        default_llm = json.loads((IDENTITY_DIR / "dante" / "id.json").read_text(encoding="utf-8")).get("llm", {})
    except (OSError, ValueError):
        pass
    identity_config = {
        "name": name,
        "role": normalized["role"],
        "description": description.strip(),
        "personality": {
            "traits": traits,
            "tone": normalized["tone"],
            "language": normalized["language"],
        },
        "llm": {
            "type": "custom_llm",
            "base_url": CONFIG.get("default_llm_base_url") or default_llm.get("base_url", ""),
            "model": CONFIG.get("default_llm_model") or default_llm.get("model", ""),
            "api_key": "",
            "temperature": normalized["temperature"],
            "max_tokens": 8192,
        },
    }
    superego_config = {
        "task_prompt": system_prompt + "\nInspect evidence before acting. Use only installed tools and verify the final result.",
        "tool_access": {"whitelist": [], "blacklist": []},
        "knowledge_access": {"whitelist": [], "blacklist": []},
        "allow_create_agent": False,
        "allow_create_identity": False,
        "allow_modify_agent": normalized["allow_self_evolution"],
        "allow_modify_identity": normalized["allow_self_evolution"],
        "allow_add_skill_to_self": normalized["allow_self_evolution"],
        "allow_add_knowledge_to_self": normalized["allow_self_evolution"],
        "allow_add_skill_to_other": False,
        "allow_add_knowledge_to_other": False,
        "allow_add_tool_to_environment": False,
        "allow_add_knowledge_to_environment": False,
    }

    blueprint = {
        "version": 1,
        "name": harness_name,
        "description": f"Visual one-shot Agent Harness for {name}: {description.strip()}",
        "roles": {
            "agent": {
                "description": description.strip(),
                "required": True,
                "identity": name,
            }
        },
        "start": "input",
        "steps": [
            {"id": "input", "type": "input", "next": "think"},
            {
                "id": "think",
                "type": "agent",
                "role": "agent",
                "on": {"tools": "act", "text": "finish"},
                "config": {"tools": "auto", "max_empty_responses": 1},
            },
            {"id": "act", "type": "tool", "role": "agent", "next": "think"},
            {"id": "finish", "type": "end", "inputs": {"value": "$last.text"}},
        ],
        "return_mode": "last",
        "max_steps": 100,
        "workspace_preview": True,
    }

    service = HarnessBlueprintService(PROJECT_ROOT)
    service.validate(blueprint)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=str(IDENTITY_DIR)))
    committed_harness = False
    copied_tools = []
    try:
        ego_dir = temporary / "ego"
        skills_dir = ego_dir / "skills"
        knowledge_dir = ego_dir / "knowledge"
        superego_dir = temporary / "superego"
        skills_dir.mkdir(parents=True)
        knowledge_dir.mkdir(parents=True)
        superego_dir.mkdir(parents=True)
        (temporary / "id.json").write_text(json.dumps(identity_config, ensure_ascii=False, indent=2), encoding="utf-8")
        (superego_dir / "config.json").write_text(json.dumps(superego_config, ensure_ascii=False, indent=2), encoding="utf-8")

        source_skills = IDENTITY_DIR / "dante" / "ego" / "skills"
        for tool in tools:
            source = source_skills / tool
            if source.is_dir() and (source / "meta.json").is_file():
                shutil.copytree(source, skills_dir / tool)
                copied_tools.append(tool)

        for tech in tech_stack:
            knowledge = knowledge_dir / tech
            knowledge.mkdir()
            (knowledge / "meta.json").write_text(json.dumps({
                "type": "knowledge",
                "name": tech,
                "title": f"{tech.title()} working notes",
                "description": f"Use this knowledge when a task concerns {tech}; update it with verified project-specific facts.",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            (knowledge / f"{tech}.txt").write_text(
                f"# {tech.title()} working notes\n\nNo project-specific facts have been learned yet. Verify before adding durable knowledge.\n",
                encoding="utf-8",
            )

        service.create(blueprint)
        committed_harness = True
        _replace_directory(temporary, agent_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        if committed_harness:
            shutil.rmtree(PROJECT_ROOT / "harness" / harness_name, ignore_errors=True)
        raise

    return {
        "status": "created",
        "identity": identity_config,
        "harness": harness_name,
        "recommended_harness": harness_name,
        "path": str(agent_dir),
        "skills": copied_tools,
        "blueprint": blueprint,
        "agent_spec": normalized,
        "next_steps": [
            f"Open {harness_name} in Studio to see the generated DAG",
            f"Bind slot agent to identity/{name} (already stored as the slot default)",
            f"Run the Harness with a concrete task and inspect every node",
            "Use manage_harness inspect → dry-run patch → patch for structural evolution",
        ],
    }


def create_agent_from_spec(spec: dict, name: str = None) -> Dict:
    """Create an Agent from an explicit model-authored, user-inspectable spec."""

    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    description = str(spec.get("description") or spec.get("purpose") or spec.get("role") or "").strip()
    if not description:
        raise ValueError("spec must include description, purpose or role")
    return create_agent_from_description(description, name=name, spec=spec)


def list_templates() -> List[Dict]:
    """List all available agent templates.

    Returns:
        List of dicts describing each template.
    """
    result = []
    for name, config in TEMPLATES.items():
        result.append({
            "name": name,
            "traits": config["traits"],
            "tools": config["tools"],
            "harness": "generated per Agent",
            "temperature": config["temperature"],
        })
    return result
