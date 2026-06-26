"""列出全局 registry 中所有已注册的 environment 和 identity 的 knowledge/tool/skill"""
import json
from pathlib import Path


REGISTRY_PATH = Path.home() / ".egoagent_registry.json"


def list_all_resources(category: str = "all"):
    if not REGISTRY_PATH.exists():
        return "Error: registry file not found at " + str(REGISTRY_PATH)

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    results = []

    show_env_knowledge = category in ("all", "env_knowledge")
    show_env_tools = category in ("all", "env_tools")
    show_id_knowledge = category in ("all", "identity_knowledge")
    show_id_skills = category in ("all", "identity_skills")

    # --- Environment resources ---
    if show_env_knowledge or show_env_tools:
        results.append("=== Environments ===")
        for env_path in registry.get("environments", []):
            env_dir = Path(env_path)
            if not env_dir.is_dir():
                continue
            env_resolved = str(env_dir.resolve())
            results.append(f"\n[ENV] {env_resolved}")

            if show_env_tools:
                tools_dir = env_dir / "tools"
                skills_dir = env_dir / "skills"
                t_dir = tools_dir if tools_dir.is_dir() else (skills_dir if skills_dir.is_dir() else None)
                if t_dir:
                    for item in sorted(t_dir.iterdir()):
                        if item.is_dir() and (item / "meta.json").exists():
                            meta = json.loads((item / "meta.json").read_text(encoding="utf-8"))
                            short_name = meta.get("name", meta.get("function", {}).get("name", item.name))
                            full_name = f"ENV<{env_resolved}>:TOOL:{short_name}"
                            desc = meta.get("description", meta.get("function", {}).get("description", ""))
                            results.append(f"    [tool] {full_name}: {desc}")

            if show_env_knowledge:
                knowledge_dir = env_dir / "knowledge"
                if knowledge_dir.is_dir():
                    for item in sorted(knowledge_dir.iterdir()):
                        if item.is_dir() and (item / "meta.json").exists():
                            meta = json.loads((item / "meta.json").read_text(encoding="utf-8"))
                            short_name = meta.get("name", item.name)
                            full_name = f"ENV<{env_resolved}>:KNOWLEDGE:{short_name}"
                            desc = meta.get("description", "")
                            results.append(f"    [knowledge] {full_name}: {desc}")

    # --- Identity resources ---
    if show_id_knowledge or show_id_skills:
        results.append("\n=== Identities ===")
        for id_path in registry.get("identities", []):
            id_dir = Path(id_path)
            if not id_dir.is_dir():
                continue

            id_resolved = str(id_dir.resolve())
            id_json = id_dir / "id.json"
            id_name = id_dir.name
            if id_json.exists():
                id_data = json.loads(id_json.read_text(encoding="utf-8"))
                id_name = id_data.get("name", id_dir.name)
            results.append(f"\n[IDENTITY] {id_name} ({id_resolved})")

            if show_id_skills:
                skills_dir = id_dir / "ego" / "skills"
                if skills_dir.is_dir():
                    for item in sorted(skills_dir.iterdir()):
                        if item.is_dir() and (item / "meta.json").exists():
                            meta = json.loads((item / "meta.json").read_text(encoding="utf-8"))
                            short_name = meta.get("name", meta.get("function", {}).get("name", item.name))
                            full_name = f"IDENTITY<{id_resolved}>:TOOL:{short_name}"
                            desc = meta.get("description", meta.get("function", {}).get("description", ""))
                            results.append(f"    [skill] {full_name}: {desc}")

            if show_id_knowledge:
                knowledge_dir = id_dir / "ego" / "knowledge"
                if knowledge_dir.is_dir():
                    for item in sorted(knowledge_dir.iterdir()):
                        if item.is_dir() and (item / "meta.json").exists():
                            meta = json.loads((item / "meta.json").read_text(encoding="utf-8"))
                            short_name = meta.get("name", item.name)
                            full_name = f"IDENTITY<{id_resolved}>:KNOWLEDGE:{short_name}"
                            desc = meta.get("description", "")
                            results.append(f"    [knowledge] {full_name}: {desc}")

    return "\n".join(results) if results else "No resources found."
