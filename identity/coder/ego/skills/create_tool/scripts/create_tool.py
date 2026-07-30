"""
为指定 identity 创建一个新工具（skill）。
写入 meta.json 声明和 Python 实现脚本。
"""
import json
from pathlib import Path


def create_tool(identity_name: str, tool_name: str, description: str,
                parameters_schema: dict, function_code: str):
    # 项目根目录
    PROJECT_ROOT = Path(__file__).resolve().parents[6]
    identity_root = PROJECT_ROOT / "identity"

    # 校验 identity 存在
    identity_dir = identity_root / identity_name
    if not identity_dir.exists():
        return f"Error: identity '{identity_name}' not found at {identity_dir}"

    # 校验 tool_name
    tool_name = tool_name.strip().replace(" ", "_").replace("-", "_")
    if not tool_name:
        return "Error: tool_name cannot be empty."

    # 检查是否已存在
    skill_dir = identity_dir / "ego" / "skills" / tool_name
    if skill_dir.exists():
        return f"Error: tool '{tool_name}' already exists for identity '{identity_name}' at {skill_dir}"

    # 校验 function_code 中包含同名函数
    if f"def {tool_name}(" not in function_code:
        return f"Error: function_code must define a function named '{tool_name}'. Expected 'def {tool_name}(...)' in the code."

    # 构建 meta.json
    meta = {
        "type": "tool",
        "name": tool_name,
        "description": description,
        "parameters": parameters_schema
    }

    # 创建目录结构
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    # 写入 meta.json
    (skill_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    # 写入脚本
    script_path = scripts_dir / f"{tool_name}.py"
    script_path.write_text(function_code, encoding="utf-8")

    return (
        f"✅ Tool '{tool_name}' created for identity '{identity_name}'!\n"
        f"Path: {skill_dir}\n"
        f"Script: {script_path}\n"
        f"Description: {description}\n\n"
        f"The tool will be available next time this identity is loaded in a harness."
    )
