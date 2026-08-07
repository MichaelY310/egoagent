"""Module for creating AI agents from natural language descriptions."""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IDENTITY_DIR = PROJECT_ROOT / "identity"

TEMPLATES = {
    "code_review": {
        "traits": ["meticulous", "constructive", "thorough"],
        "tools": ["read_file", "search_files", "patch_file"],
        "harness": "react_single",
        "temperature": 0.3,
    },
    "coding": {
        "traits": ["efficient", "pragmatic", "test_driven"],
        "tools": ["read_file", "write_file", "patch_file", "search_files", "run_command"],
        "harness": "coder_react",
        "temperature": 0.5,
    },
    "research": {
        "traits": ["curious", "analytical", "systematic"],
        "tools": ["read_file", "search_files", "write_file"],
        "harness": "research_loop",
        "temperature": 0.7,
    },
    "creative": {
        "traits": ["creative", "innovative", "open_minded"],
        "tools": ["read_file", "write_file"],
        "harness": "creative_roundtable",
        "temperature": 0.9,
    },
    "devops": {
        "traits": ["systematic", "security_conscious", "efficient"],
        "tools": ["run_command", "read_file", "write_file", "patch_file"],
        "harness": "react_single",
        "temperature": 0.3,
    },
    "testing": {
        "traits": ["thorough", "systematic", "edge_case_aware"],
        "tools": ["read_file", "write_file", "run_command", "search_files"],
        "harness": "react_single",
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

_TECH_KEYWORDS = {
    "react": {"tools_add": ["npm_run"]},
    "vue": {"tools_add": ["npm_run"]},
    "typescript": {"tools_add": ["npm_run"]},
    "node": {"tools_add": ["npm_run"]},
    "python": {"tools_add": ["pytest"]},
    "rust": {"tools_add": ["cargo_build"]},
    "go": {"tools_add": ["go_build"]},
    "docker": {"tools_add": ["docker_run"]},
}


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


def create_agent_from_description(description: str, name: str = None) -> Dict:
    """Create an AI agent from a natural language description.

    Args:
        description: Natural language description of the desired agent.
        name: Optional name for the agent. Generated if not provided.

    Returns:
        Dict with status, identity config, recommended harness, path, and next_steps.
    """
    template_name = _match_template(description)
    template = TEMPLATES[template_name]
    tech_stack = _detect_tech_stack(description)

    if name is None:
        name = _generate_name(description, template_name)

    # Handle name conflicts by adding suffix
    agent_dir = IDENTITY_DIR / name
    if agent_dir.exists():
        suffix = int(time.time()) % 10000
        name = f"{name}_{suffix}"
        agent_dir = IDENTITY_DIR / name

    # Build tools list with tech-specific additions
    tools = list(template["tools"])
    for tech in tech_stack:
        for tool in _TECH_KEYWORDS[tech]["tools_add"]:
            if tool not in tools:
                tools.append(tool)

    # Create identity directory structure
    ego_dir = agent_dir / "ego"
    skills_dir = ego_dir / "skills"
    knowledge_dir = ego_dir / "knowledge"
    superego_dir = agent_dir / "superego"

    os.makedirs(skills_dir, exist_ok=True)
    os.makedirs(knowledge_dir, exist_ok=True)
    os.makedirs(superego_dir, exist_ok=True)

    # Build identity config
    traits = list(template["traits"])
    system_prompt = _build_system_prompt(template_name, traits, tech_stack)

    identity_config = {
        "name": name,
        "template": template_name,
        "traits": traits,
        "tools": tools,
        "temperature": template["temperature"],
        "tech_stack": tech_stack,
        "created_at": time.time(),
    }

    # Write id.json
    id_path = agent_dir / "id.json"
    with open(id_path, "w", encoding="utf-8") as f:
        json.dump(identity_config, f, indent=2, ensure_ascii=False)

    # Write system_prompt.txt
    prompt_path = ego_dir / "system_prompt.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(system_prompt)

    # Write tools.json
    tools_config = [{"name": t, "enabled": True} for t in tools]
    tools_path = ego_dir / "tools.json"
    with open(tools_path, "w", encoding="utf-8") as f:
        json.dump(tools_config, f, indent=2, ensure_ascii=False)

    # Create knowledge base placeholders for detected tech
    for tech in tech_stack:
        kb_path = knowledge_dir / f"{tech}.md"
        with open(kb_path, "w", encoding="utf-8") as f:
            f.write(f"# {tech.capitalize()} Knowledge Base\n\nAdd {tech} knowledge here.\n")

    return {
        "status": "created",
        "identity": identity_config,
        "recommended_harness": template["harness"],
        "path": str(agent_dir),
        "next_steps": [
            f"Edit {prompt_path} to customize the system prompt",
            f"Add knowledge files to {knowledge_dir}",
            f"Configure tools in {tools_path}",
            f"Run with harness: {template['harness']}",
        ],
    }


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
            "harness": config["harness"],
            "temperature": config["temperature"],
        })
    return result
