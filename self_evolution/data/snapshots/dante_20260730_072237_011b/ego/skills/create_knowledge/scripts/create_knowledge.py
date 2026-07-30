"""
为指定 identity 创建一个新的知识文件。
知识会在 agent 加载时自动注入上下文。
"""
import json
from pathlib import Path


def create_knowledge(identity_name: str, knowledge_name: str, content: str,
                     filename: str = None):
    # 项目根目录
    PROJECT_ROOT = Path(__file__).resolve().parents[6]
    identity_root = PROJECT_ROOT / "identity"

    # 校验 identity 存在
    identity_dir = identity_root / identity_name
    if not identity_dir.exists():
        return f"Error: identity '{identity_name}' not found at {identity_dir}"

    # 校验 knowledge_name
    knowledge_name = knowledge_name.strip().replace(" ", "_").replace("-", "_")
    if not knowledge_name:
        return "Error: knowledge_name cannot be empty."

    if not content or not content.strip():
        return "Error: content cannot be empty."

    # 检查是否已存在
    knowledge_dir = identity_dir / "ego" / "knowledge" / knowledge_name
    if knowledge_dir.exists():
        return f"Error: knowledge '{knowledge_name}' already exists for identity '{identity_name}' at {knowledge_dir}"

    # 创建目录
    knowledge_dir.mkdir(parents=True)

    # 确定文件名
    if not filename:
        filename = f"{knowledge_name}.txt"

    # 写入知识文件
    file_path = knowledge_dir / filename
    file_path.write_text(content, encoding="utf-8")

    return (
        f"✅ Knowledge '{knowledge_name}' created for identity '{identity_name}'!\n"
        f"Path: {file_path}\n"
        f"Size: {len(content)} chars\n\n"
        f"The knowledge will be available next time this identity is loaded in a harness."
    )
