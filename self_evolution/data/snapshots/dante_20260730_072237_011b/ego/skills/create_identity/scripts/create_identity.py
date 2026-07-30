"""
从零创建一个新的 agent identity，包含完整目录结构。
"""
import json
import shutil
from pathlib import Path


def create_identity(name: str, role: str, description: str,
                    personality_traits: list = None,
                    personality_tone: str = "professional",
                    language: str = "zh",
                    llm_model: str = None,
                    llm_base_url: str = None,
                    task_prompt: str = None,
                    skills_to_copy_from: str = None):
    from config import CONFIG

    # 确定 identity 根目录
    identity_root = Path(__file__).resolve().parents[6] / "identity"
    if not identity_root.exists():
        return f"Error: identity root directory not found: {identity_root}"

    # 校验名称
    name = name.strip().replace(" ", "_").replace("-", "_")
    if not name:
        return "Error: name cannot be empty."

    identity_dir = identity_root / name
    if identity_dir.exists():
        return f"Error: identity '{name}' already exists at {identity_dir}."

    # 获取默认 LLM 配置
    default_base_url = CONFIG.get("default_llm_base_url", "http://[fdbd:dc05:10:10a::27]:9638/v1")
    default_model = CONFIG.get("default_llm_model", "Qwen3-8B-yangyuan")

    # 构建 id.json
    id_data = {
        "name": name,
        "role": role,
        "description": description,
        "personality": {
            "traits": personality_traits or ["helpful", "professional"],
            "tone": personality_tone,
            "language": language,
        },
        "llm": {
            "type": "custom_llm",
            "base_url": llm_base_url or default_base_url,
            "model": llm_model or default_model,
            "api_key": "",
            "temperature": 0.7,
            "max_tokens": 8192,
        },
    }

    # 构建 superego config
    superego_config = {
        "task_prompt": task_prompt or "",
        "tool_access": {"whitelist": [], "blacklist": []},
        "knowledge_access": {"whitelist": [], "blacklist": []},
        "allow_create_agent": True,
        "allow_create_identity": True,
        "allow_modify_agent": False,
        "allow_modify_identity": False,
        "allow_add_skill_to_self": True,
        "allow_add_knowledge_to_self": True,
        "allow_add_skill_to_other": False,
        "allow_add_knowledge_to_other": False,
        "allow_add_tool_to_environment": False,
        "allow_add_knowledge_to_environment": False,
    }

    # 创建目录结构
    identity_dir.mkdir(parents=True)
    (identity_dir / "ego" / "skills").mkdir(parents=True)
    (identity_dir / "ego" / "knowledge").mkdir(parents=True)
    (identity_dir / "superego").mkdir(parents=True)

    # 写入 id.json
    (identity_dir / "id.json").write_text(
        json.dumps(id_data, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    # 写入 superego/config.json
    (identity_dir / "superego" / "config.json").write_text(
        json.dumps(superego_config, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    # 复制 skills（如果指定）
    copied_skills = []
    if skills_to_copy_from:
        sources = [s.strip() for s in skills_to_copy_from.split(",") if s.strip()]
        for src_name in sources:
            src_skills_dir = identity_root / src_name / "ego" / "skills"
            if not src_skills_dir.exists():
                continue
            for skill_dir in src_skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                dest = identity_dir / "ego" / "skills" / skill_dir.name
                if not dest.exists():
                    shutil.copytree(str(skill_dir), str(dest))
                    copied_skills.append(skill_dir.name)

    result = (
        f"✅ Identity '{name}' created successfully!\n"
        f"Path: {identity_dir}\n"
        f"Role: {role}\n"
        f"Description: {description}\n"
        f"Language: {language}\n"
        f"LLM: {id_data['llm']['model']} @ {id_data['llm']['base_url']}\n"
    )

    if copied_skills:
        result += f"Copied skills: {', '.join(copied_skills)}\n"

    result += (
        f"\nYou can now use this identity in create_harness:\n"
        f"  agents: \"slot_name:identity/{name}\""
    )

    return result
