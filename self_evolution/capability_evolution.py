"""Identity capability evolution with inspectable, reversible transactions.

Harness structure, Skills and Knowledge are different kinds of evolution.  The
Blueprint service owns graph changes; this module owns installing reusable EGO
capabilities and creating isolated worker Agents when that is cheaper than
repeating a long tool trajectory in the parent context.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from harness_blueprint import BlueprintError, HarnessBlueprintService


PACKS = {
    "paper_library": {
        "description": "Index and retrieve downloaded PDF/TXT/Markdown papers locally before web search.",
        "creates": ["skill:local_paper_search", "knowledge:local_papers_first"],
    },
    "delegated_search": {
        "description": "Create an isolated result-only search Agent/Harness and expose it as one parent tool.",
        "creates": ["skill:delegate_search", "knowledge:delegated_search_policy", "identity:search_worker", "harness:result_only_search"],
    },
}

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,79}$")


class CapabilityEvolutionError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(
            item for item in path.rglob("*")
            if item.is_file()
            and "__pycache__" not in item.parts
            and item.suffix.lower() not in {".pyc", ".pyo"}
        ):
            digest.update(child.relative_to(path).as_posix().encode())
            digest.update(child.read_bytes())
    return digest.hexdigest()[:16]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def analyze_evolution_need(observations: Any, *, workspace: str = "") -> dict:
    """Return deterministic recommendations before asking a weak model to act."""
    if isinstance(observations, (dict, list)):
        text = json.dumps(observations, ensure_ascii=False)
    else:
        text = str(observations or "")
    lower = text.lower()
    recommendations = []

    paper_hits = sum(token in lower for token in (".pdf", "paper", "论文", "arxiv", "文献"))
    if paper_hits:
        recommendations.append({
            "kind": "identity_capability",
            "pack": "paper_library",
            "confidence": min(0.98, 0.62 + paper_hits * 0.1),
            "reason": "The task contains local-paper signals; bounded retrieval avoids losing supplied evidence and avoids injecting whole PDFs.",
        })

    search_mentions = len(re.findall(r"search|搜索|检索|browser|网页", lower))
    failure_mentions = len(re.findall(r"failed|failure|timeout|失败|超时|重试", lower))
    if search_mentions >= 2 or (search_mentions and failure_mentions >= 2):
        recommendations.append({
            "kind": "identity_capability",
            "pack": "delegated_search",
            "confidence": min(0.97, 0.55 + 0.06 * search_mentions + 0.05 * failure_mentions),
            "reason": "Repeated search trajectories should run in an isolated sub-Agent; the parent receives only the final evidence summary.",
        })

    if any(token in lower for token in ("context length", "context is too long", "too long", "token", "上下文", "太长", "compaction")):
        recommendations.append({
            "kind": "harness_patch",
            "recipe": "context_guard",
            "confidence": 0.78,
            "reason": "Add a Context auto_compact node before the Agent rather than accumulating old observations.",
            "suggested_steps": ["inspect Harness Blueprint", "insert context step", "route it before Agent", "run the same long-context evaluation"],
        })

    repeated_actions = re.findall(r"(?:tool|action|工具|操作)[:= ]+([\w.-]+)", lower)
    if len(repeated_actions) >= 3 and len(set(repeated_actions[-3:])) == 1:
        recommendations.append({
            "kind": "skill_extraction",
            "recipe": "repeated_sequence_to_skill",
            "confidence": 0.82,
            "reason": "The same operation is repeated; extract a bounded deterministic Skill and store a Knowledge rule describing when to call it.",
        })

    if any(token in lower for token in ("delete", "publish", "deploy", "删除", "发布", "部署")):
        recommendations.append({
            "kind": "harness_patch",
            "recipe": "risk_gate",
            "confidence": 0.72,
            "reason": "Put snapshot/checkpoint and Human Approval before hard-to-recover side effects.",
        })

    if failure_mentions >= 3:
        recommendations.append({
            "kind": "evaluation",
            "recipe": "failure_distillation",
            "confidence": 0.75,
            "reason": "Distill repeated failures into a short cautionary Knowledge item only after reproducing and verifying the cause.",
        })

    return {
        "ok": True,
        "workspace": workspace,
        "recommendations": sorted(recommendations, key=lambda item: -item["confidence"]),
        "principle": "Prefer the smallest reversible capability change: Knowledge for durable facts, Skill for deterministic repeated work, sub-Agent for isolated long trajectories, Harness patch for control-flow failures.",
    }


class CapabilityEvolutionService:
    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.identity_root = self.root / "identity"
        self.pack_root = self.root / "self_evolution" / "capability_packs"
        self.transaction_root = self.root / "self_evolution" / "data" / "capability_transactions"

    def _identity(self, name: str) -> Path:
        if not _SAFE_NAME.fullmatch(str(name or "")):
            raise CapabilityEvolutionError("invalid identity name")
        path = (self.identity_root / name).resolve()
        if path.parent != self.identity_root.resolve() or not (path / "id.json").is_file():
            raise CapabilityEvolutionError(f"identity not found: {name}")
        return path

    def inspect(self, name: str) -> dict:
        identity = self._identity(name)
        skills = sorted(path.name for path in (identity / "ego" / "skills").iterdir() if path.is_dir()) if (identity / "ego" / "skills").is_dir() else []
        knowledge = sorted(path.name for path in (identity / "ego" / "knowledge").iterdir() if path.is_dir()) if (identity / "ego" / "knowledge").is_dir() else []
        installed = []
        if "local_paper_search" in skills and "local_papers_first" in knowledge:
            installed.append("paper_library")
        if "delegate_search" in skills and "delegated_search_policy" in knowledge:
            installed.append("delegated_search")
        return {"ok": True, "identity": name, "skills": skills, "knowledge": knowledge, "installed_packs": installed, "available_packs": PACKS}

    def install(self, name: str, pack: str, *, dry_run: bool = False, reason: str = "") -> dict:
        identity = self._identity(name)
        if pack not in PACKS:
            raise CapabilityEvolutionError(f"unknown capability pack: {pack}")
        transaction_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        created: list[str] = []
        preview = []
        try:
            if pack == "paper_library":
                sources = [
                    (self.pack_root / pack / "skills" / "local_paper_search", identity / "ego" / "skills" / "local_paper_search"),
                    (self.pack_root / pack / "knowledge" / "local_papers_first", identity / "ego" / "knowledge" / "local_papers_first"),
                ]
                for source, target in sources:
                    if target.exists():
                        if _fingerprint(source) != _fingerprint(target):
                            raise CapabilityEvolutionError(f"capability target exists with different content: {target}")
                        preview.append({"path": str(target.relative_to(self.root)), "action": "already_installed"})
                    else:
                        preview.append({"path": str(target.relative_to(self.root)), "action": "create"})
                        if not dry_run:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copytree(source, target)
                            created.append(str(target.relative_to(self.root)))
            else:
                generated = self._delegated_search_resources(name)
                for target, kind, content in generated:
                    if target.exists():
                        raise CapabilityEvolutionError(f"delegated-search target already exists: {target.relative_to(self.root)}")
                    preview.append({"path": str(target.relative_to(self.root)), "action": "create", "kind": kind})
                if not dry_run:
                    for target, kind, content in generated:
                        if kind == "directory_copy":
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copytree(Path(content), target)
                        elif kind == "directory":
                            target.mkdir(parents=True, exist_ok=False)
                        else:
                            _atomic_write(target, str(content))
                        created.append(str(target.relative_to(self.root)))
                    harness_blueprint = self._delegated_search_blueprint(name)
                    created_result = HarnessBlueprintService(self.root).create(harness_blueprint)
                    created.append(str((self.root / "harness" / created_result["harness"]).relative_to(self.root)))

            transaction = {
                "version": 1,
                "id": transaction_id,
                "timestamp": time.time(),
                "identity": name,
                "pack": pack,
                "reason": reason,
                "created": created,
                "preview": preview,
                "fingerprints": {
                    item: _fingerprint(self.root / item) for item in created if (self.root / item).exists()
                },
            }
            if not dry_run:
                self.transaction_root.mkdir(parents=True, exist_ok=True)
                _atomic_write(self.transaction_root / f"{transaction_id}.json", _json(transaction))
            return {"ok": True, "action": "install", "identity": name, "pack": pack, "transaction_id": transaction_id, "changes": preview, "dry_run": dry_run}
        except BaseException:
            if not dry_run:
                for relative in reversed(created):
                    path = (self.root / relative).resolve()
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    elif path.is_file():
                        try:
                            path.unlink()
                        except OSError:
                            pass
            raise

    def rollback(self, transaction_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(transaction_id or "")):
            raise CapabilityEvolutionError("invalid transaction id")
        path = self.transaction_root / f"{transaction_id}.json"
        if not path.is_file():
            raise CapabilityEvolutionError(f"transaction not found: {transaction_id}")
        tx = json.loads(path.read_text(encoding="utf-8"))
        for relative, expected in tx.get("fingerprints", {}).items():
            target = (self.root / relative).resolve()
            if self.root != target and self.root not in target.parents:
                raise CapabilityEvolutionError("transaction path escapes project root")
            if target.exists() and _fingerprint(target) != expected:
                raise CapabilityEvolutionError(f"rollback conflict; resource changed after installation: {relative}")
        removed = []
        for relative in reversed(tx.get("created", [])):
            target = (self.root / relative).resolve()
            if target.is_dir():
                shutil.rmtree(target)
                removed.append(relative)
            elif target.is_file():
                target.unlink()
                removed.append(relative)
        return {"ok": True, "action": "rollback", "transaction_id": transaction_id, "identity": tx.get("identity"), "pack": tx.get("pack"), "removed": removed}

    def _delegated_search_names(self, parent: str):
        return f"{parent}_search_worker", f"{parent}_result_only_search"

    def _delegated_search_blueprint(self, parent: str):
        worker, harness = self._delegated_search_names(parent)
        return {
            "version": 1,
            "name": harness,
            "description": "Isolated search trajectory; only the final evidence summary returns to the parent Agent.",
            "roles": {"searcher": {"description": "Evidence-only search worker", "required": True, "identity": worker}},
            "start": "input",
            "steps": [
                {"id": "input", "type": "input", "next": "search"},
                {"id": "search", "type": "agent", "role": "searcher", "on": {"tools": "act", "text": "finish"}, "config": {"tools": "auto", "max_empty_responses": 1}},
                {"id": "act", "type": "tool", "role": "searcher", "next": "search"},
                {"id": "finish", "type": "end", "inputs": {"value": "$last.text"}},
            ],
            "return_mode": "last",
            "max_steps": 80,
        }

    def _delegated_search_resources(self, parent: str):
        identity = self._identity(parent)
        worker_name, harness_name = self._delegated_search_names(parent)
        worker = self.identity_root / worker_name
        delegate = identity / "ego" / "skills" / "delegate_search"
        knowledge = identity / "ego" / "knowledge" / "delegated_search_policy"
        parent_id = json.loads((identity / "id.json").read_text(encoding="utf-8"))
        worker_id = copy.deepcopy(parent_id)
        worker_id.update({
            "name": worker_name,
            "role": "isolated evidence search worker",
            "description": "Search and read evidence. Return only concise findings with source paths or URLs; never narrate failed attempts unless they affect confidence.",
        })
        if isinstance(worker_id.get("llm"), dict):
            worker_id["llm"]["api_key"] = ""
        superego = {
            "task_prompt": "Search for the requested evidence. Use available search/read/browser tools. Return only findings, citations, unresolved gaps and confidence. Do not chat, plan aloud or modify the parent workspace.",
            "tool_access": {"whitelist": [], "blacklist": ["write", "patch", "end_session"]},
            "knowledge_access": {"whitelist": [], "blacklist": []},
            "allow_create_agent": False,
            "allow_create_identity": False,
            "allow_modify_agent": False,
            "allow_modify_identity": False,
            "allow_add_skill_to_self": False,
            "allow_add_knowledge_to_self": False,
        }
        source_skills = self.identity_root / "dante" / "ego" / "skills"
        resources = [
            (worker, "directory", ""),
            (worker / "id.json", "file", _json(worker_id)),
            (worker / "superego" / "config.json", "file", _json(superego)),
        ]
        for skill_name in ("read", "search"):
            source = source_skills / skill_name
            if source.is_dir():
                resources.append((worker / "ego" / "skills" / skill_name, "directory_copy", str(source)))
        browser_source = self.identity_root / "browser_operator" / "ego" / "skills" / "browser"
        if browser_source.is_dir():
            resources.append((worker / "ego" / "skills" / "browser", "directory_copy", str(browser_source)))

        meta = {
            "type": "tool",
            "name": "delegate_search",
            "description": "Run repeated searching in an isolated sub-Agent and return only its final evidence summary. Its internal attempts do not enter the parent Agent context, while Studio can still visualize the sub-session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Exact research question and required evidence"},
                    "max_result_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
                },
                "required": ["query"],
            },
        }
        script = f'''"""Generated result-only search delegation tool."""\nfrom pathlib import Path\nfrom utils import load_script\n\ndef delegate_search(query: str, max_result_chars: int = 12000):\n    create_path = Path(__file__).resolve().parents[2] / "create_harness" / "scripts" / "create_harness.py"\n    create_harness = load_script(create_path, "create_harness")\n    if not create_harness:\n        return "Error: create_harness capability is missing."\n    return create_harness(\n        harness_dir="harness/{harness_name}",\n        agents="searcher:identity/{worker_name}",\n        initial_message=query,\n        inherit_conversation=False,\n        return_mode="last",\n        max_result_chars=max_result_chars,\n        include_metadata=False,\n    )\n'''
        policy = f"For tasks needing several searches, call delegate_search once with a precise evidence question. The isolated worker {worker_name} may make many attempts, but only its final result enters this Agent's context. Ask it for source URLs/paths and unresolved gaps. Do not repeat the same searches in the parent unless the returned evidence is insufficient."
        resources.extend([
            (delegate, "directory", ""),
            (delegate / "meta.json", "file", _json(meta)),
            (delegate / "scripts" / "delegate_search.py", "file", script),
            (knowledge, "directory", ""),
            (knowledge / "meta.json", "file", _json({"type": "knowledge", "name": "delegated_search_policy", "title": "Use isolated search Agent", "description": "When and why to delegate repeated searches"})),
            (knowledge / "delegated_search_policy.txt", "file", policy + "\n"),
        ])
        create_harness_source = source_skills / "create_harness"
        create_harness_target = identity / "ego" / "skills" / "create_harness"
        if not create_harness_target.exists() and create_harness_source.is_dir():
            resources.append((create_harness_target, "directory_copy", str(create_harness_source)))
        return resources
