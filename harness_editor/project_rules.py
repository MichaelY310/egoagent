"""
Project Rules and Cross-Session Memory module.

Provides:
1. Project Rules System - manages .egoagent/rules/*.md files
2. Cross-Session Memory - manages .egoagent/memory/*.json files
"""

import os
import json
import time
from typing import List, Dict

DEFAULT_WORKSPACE = "/home/tiger/egoagent"


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


def get_effective_rules_prompt(workspace_path: str = DEFAULT_WORKSPACE) -> str:
    """Combines all rules into a single string suitable for injection into system prompts."""
    rules = get_rules(workspace_path)
    if not rules:
        return ""
    parts = []
    for rule in rules:
        name = rule["name"]
        content = rule["content"]
        parts.append(f"[Project Rule: {name}]\n{content}\n")
    return "\n".join(parts)


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
    return "\n\n".join(parts)
