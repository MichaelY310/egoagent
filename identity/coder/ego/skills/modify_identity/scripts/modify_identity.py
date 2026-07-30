"""
修改指定 identity 的配置字段。
"""
import json
from pathlib import Path


def modify_identity(identity_name: str, field: str, value: str):
    # 项目根目录
    project_root = Path(__file__).resolve().parents[6]
    identity_dir = project_root / "identity" / identity_name

    if not identity_dir.exists():
        return f"Error: identity '{identity_name}' not found at {identity_dir}"

    # 确定要修改的文件和字段路径
    if field == "task_prompt":
        config_path = identity_dir / "superego" / "config.json"
        if not config_path.exists():
            return f"Error: superego config not found at {config_path}"

        data = json.loads(config_path.read_text(encoding="utf-8"))
        old_value = data.get("task_prompt", "")
        data["task_prompt"] = value
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

    else:
        config_path = identity_dir / "id.json"
        if not config_path.exists():
            return f"Error: id.json not found at {config_path}"

        data = json.loads(config_path.read_text(encoding="utf-8"))

        if field in ("temperature", "max_tokens"):
            # 这些字段在 llm 子对象中，且为数值类型
            if "llm" not in data:
                return f"Error: 'llm' section not found in id.json"
            old_value = data["llm"].get(field, "")
            if field == "temperature":
                data["llm"][field] = float(value)
            else:
                data["llm"][field] = int(value)
        elif field in ("description", "role"):
            old_value = data.get(field, "")
            data[field] = value
        else:
            return f"Error: unsupported field '{field}'"

        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")

    return (
        f"✅ Identity '{identity_name}' updated successfully.\n"
        f"Field: {field}\n"
        f"Old value: {old_value}\n"
        f"New value: {value}\n"
        f"File: {config_path}"
    )
