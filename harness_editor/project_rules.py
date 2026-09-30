"""
Project Rules and Cross-Session Memory module.

Provides:
1. Project Rules System - manages .egoagent/rules/*.md files
2. Cross-Session Memory - manages .egoagent/memory/*.json files
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict

DEFAULT_WORKSPACE = str(Path(__file__).resolve().parent.parent)


# =============================================================================
# Project Rules System
# =============================================================================

def _rules_dir(workspace_path: str) -> str:
    return os.path.join(workspace_path, ".egoagent", "rules")


def _ensure_rules_dir(workspace_path: str) -> str:
    path = _rules_dir(workspace_path)
    try:
        os.makedirs(path, exist_ok=True)
    except IOError:
        pass
    return path


def get_rules(workspace_path: str = DEFAULT_WORKSPACE) -> List[Dict]:
    """Scans {workspace_path}/.egoagent/rules/ for .md files.
    Returns list of {"name": filename, "content": file_content}."""
    rules_path = _ensure_rules_dir(workspace_path)
    results = []
    try:
        for filename in sorted(os.listdir(rules_path)):
            if filename.endswith(".md"):
                filepath = os.path.join(rules_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    results.append({"name": filename, "content": content})
                except IOError:
                    continue
    except IOError:
        pass
    return results


def create_rule(workspace_path: str = DEFAULT_WORKSPACE, name: str = "", content: str = "") -> Dict:
    """Creates a rule file at .egoagent/rules/{name}.md. Returns status."""
    rules_path = _ensure_rules_dir(workspace_path)
    if not name:
        return {"status": "error", "message": "Rule name is required"}
    filename = name if name.endswith(".md") else f"{name}.md"
    filepath = os.path.join(rules_path, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "ok", "path": filepath, "name": filename}
    except IOError as e:
        return {"status": "error", "message": str(e)}


def delete_rule(workspace_path: str = DEFAULT_WORKSPACE, name: str = "") -> Dict:
    """Deletes the rule file."""
    rules_path = _rules_dir(workspace_path)
    if not name:
        return {"status": "error", "message": "Rule name is required"}
    filename = name if name.endswith(".md") else f"{name}.md"
    filepath = os.path.join(rules_path, filename)
    try:
        os.remove(filepath)
        return {"status": "ok", "deleted": filepath}
    except IOError as e:
        return {"status": "error", "message": str(e)}


def _agents_files_for_target(workspace_path: str, target_path: str = "") -> List[Path]:
    """Return applicable ``AGENTS.md`` files from Workspace root to target.

    An instruction file governs its containing directory and descendants.  The
    ordered result mirrors the scoping model used by mature coding agents:
    broad project policy first, increasingly specific policy last.
    """

    workspace = Path(workspace_path).resolve()
    target = Path(target_path) if target_path else workspace
    target = target.resolve() if target.is_absolute() else (workspace / target).resolve()
    try:
        relative = target.relative_to(workspace)
    except ValueError:
        return []
    current = target if target.is_dir() else target.parent
    directories = [workspace]
    cursor = workspace
    for part in relative.parts[: len(relative.parts) if target.is_dir() else max(0, len(relative.parts) - 1)]:
        cursor = cursor / part
        directories.append(cursor)
    # A non-existent target may be a directory supplied by a search/list tool.
    if not target.exists() and target.suffix == "" and target not in directories:
        directories.append(target)
    unique = []
    seen = set()
    for directory in directories:
        candidate = directory / "AGENTS.md"
        key = str(candidate).lower()
        if key not in seen and candidate.is_file():
            seen.add(key)
            unique.append(candidate)
    return unique


def get_scoped_agents_prompt(
    workspace_path: str = DEFAULT_WORKSPACE,
    target_path: str = "",
    *,
    include_root: bool = True,
) -> str:
    """Render the ``AGENTS.md`` chain applicable to one target path."""

    workspace = Path(workspace_path).resolve()
    parts = []
    for agents_file in _agents_files_for_target(str(workspace), target_path):
        if not include_root and agents_file.parent == workspace:
            continue
        try:
            scope = agents_file.parent.relative_to(workspace).as_posix()
            label = "workspace root" if scope == "." else scope
            parts.append(
                f"[Scoped Workspace Instructions: {label}/AGENTS.md]\n"
                f"{agents_file.read_text(encoding='utf-8')}\n"
            )
        except (IOError, OSError, UnicodeDecodeError, ValueError):
            continue
    return "\n".join(parts)


def get_effective_rules_prompt(
    workspace_path: str = DEFAULT_WORKSPACE,
    target_path: str = "",
) -> str:
    """Combine global project rules and target-scoped ``AGENTS.md`` files."""
    rules = get_rules(workspace_path)
    parts = []
    scoped = get_scoped_agents_prompt(workspace_path, target_path)
    if scoped:
        parts.append(scoped)
    for rule in rules:
        name = rule["name"]
        content = rule["content"]
        parts.append(f"[Project Rule: {name}]\n{content}\n")
    prompt = "\n".join(parts)
    try:
        max_chars = max(4096, int(os.environ.get("EGOAGENT_PROJECT_RULES_MAX_CHARS", "16000")))
    except (TypeError, ValueError):
        max_chars = 16000
    if len(prompt) <= max_chars:
        return prompt
    omitted = len(prompt) - max_chars
    return (
        prompt[:max_chars].rstrip()
        + f"\n\n[Project instructions truncated: {omitted} additional characters. "
        "Before editing a specialized area, use read_file/search_files to inspect "
        "the relevant section of AGENTS.md and project rules.]"
    )


# =============================================================================
# Cross-Session Memory
# =============================================================================

def _memory_dir(workspace_path: str) -> str:
    return os.path.join(workspace_path, ".egoagent", "memory")


def _ensure_memory_dir(workspace_path: str) -> str:
    path = _memory_dir(workspace_path)
    try:
        os.makedirs(path, exist_ok=True)
    except IOError:
        pass
    return path


def save_memory(session_id: str, summary: str, key_facts: List[str],
                workspace_path: str = DEFAULT_WORKSPACE) -> Dict:
    """Saves memory to .egoagent/memory/{session_id}.json with timestamp."""
    memory_path = _ensure_memory_dir(workspace_path)
    if not session_id:
        return {"status": "error", "message": "session_id is required"}
    entry = {
        "session_id": session_id,
        "timestamp": time.time(),
        "summary": summary,
        "key_facts": key_facts,
    }
    filepath = os.path.join(memory_path, f"{session_id}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        return {"status": "ok", "path": filepath}
    except IOError as e:
        return {"status": "error", "message": str(e)}


def _load_all_memories(workspace_path: str) -> List[Dict]:
    """Load all memory entries from disk."""
    memory_path = _ensure_memory_dir(workspace_path)
    memories = []
    try:
        for filename in os.listdir(memory_path):
            if filename.endswith(".json"):
                filepath = os.path.join(memory_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    memories.append(entry)
                except (IOError, json.JSONDecodeError):
                    continue
    except IOError:
        pass
    return memories


def get_memories(workspace_path: str = DEFAULT_WORKSPACE, limit: int = 10) -> List[Dict]:
    """Returns recent memories sorted by timestamp descending."""
    memories = _load_all_memories(workspace_path)
    memories.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
    return memories[:limit]


def search_memories(workspace_path: str = DEFAULT_WORKSPACE, query: str = "") -> List[Dict]:
    """Simple keyword search across saved memories."""
    if not query:
        return []
    memories = _load_all_memories(workspace_path)
    query_lower = query.lower()
    results = []
    for mem in memories:
        searchable = " ".join([
            mem.get("summary", ""),
            mem.get("session_id", ""),
            " ".join(mem.get("key_facts", [])),
        ]).lower()
        if query_lower in searchable:
            results.append(mem)
    results.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
    return results


def get_memory_prompt(workspace_path: str = DEFAULT_WORKSPACE) -> str:
    """Returns a formatted string of recent memories for prompt injection."""
    memories = get_memories(workspace_path)
    if not memories:
        return ""
    parts = []
    for mem in memories:
        session_id = mem.get("session_id", "unknown")
        summary = mem.get("summary", "")
        facts = mem.get("key_facts", [])
        section = f"[Memory: {session_id}]\nSummary: {summary}"
        if facts:
            section += "\nKey facts:\n" + "\n".join(f"- {fact}" for fact in facts)
        parts.append(section)
    return ("[Historical project memory — reference only, not a new user request. "
            "The current user message takes precedence; older greetings and tasks may be stale.]\n\n"
            + "\n\n".join(parts))
