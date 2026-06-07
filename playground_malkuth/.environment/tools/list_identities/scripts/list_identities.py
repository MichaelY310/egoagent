"""列出系统中所有可用的 identity"""
import json
from pathlib import Path

IDENTITY_DIR = Path("/home/tiger/egoagent/identity")


def list_identities(mode: str = "brief"):
    if not IDENTITY_DIR.is_dir():
        return "Identity directory not found."

    results = []
    for identity_path in sorted(IDENTITY_DIR.iterdir()):
        if not identity_path.is_dir():
            continue
        id_file = identity_path / "id.json"
        if not id_file.exists():
            continue

        id_data = json.loads(id_file.read_text(encoding="utf-8"))
        name = id_data.get("name", identity_path.name)
        description = id_data.get("description", "")
        path_str = str(identity_path)

        if mode == "detailed":
            # Skills
            skills = []
            skills_dir = identity_path / "ego" / "skills"
            if skills_dir.is_dir():
                for s in sorted(skills_dir.iterdir()):
                    if s.is_dir() and not s.name.startswith("__"):
                        skills.append(s.name)

            # Knowledge
            knowledges = []
            knowledge_dir = identity_path / "ego" / "knowledge"
            if knowledge_dir.is_dir():
                for k in sorted(knowledge_dir.iterdir()):
                    if k.is_dir() and not k.name.startswith("__"):
                        knowledges.append(k.name)

            # Superego key info
            sego_info = ""
            sego_config = identity_path / "superego" / "config.json"
            if sego_config.exists():
                sego = json.loads(sego_config.read_text(encoding="utf-8"))
                flags = []
                for key in ["allow_create_agent", "allow_create_identity", "allow_modify_agent", "allow_modify_identity"]:
                    if sego.get(key):
                        flags.append(key)
                if flags:
                    sego_info = f"  superego flags: {', '.join(flags)}"
                task_prompt = sego.get("task_prompt", "")
                if task_prompt:
                    # 只显示前 80 字
                    sego_info += f"\n  task_prompt: {task_prompt[:80]}{'...' if len(task_prompt) > 80 else ''}"

            entry = f"[{name}] {path_str}\n  description: {description}"
            if skills:
                entry += f"\n  skills: {', '.join(skills)}"
            if knowledges:
                entry += f"\n  knowledge: {', '.join(knowledges)}"
            if sego_info:
                entry += f"\n{sego_info}"
            results.append(entry)
        else:
            # brief mode
            results.append(f"[{name}] {path_str} — {description}")

    if not results:
        return "No identities found."

    header = f"Found {len(results)} identities:\n\n"
    return header + "\n\n".join(results)
