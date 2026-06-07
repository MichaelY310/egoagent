"""复制一个 identity 到同目录下，更新 id.json 中的名字"""
import json
import shutil
from pathlib import Path

IDENTITY_DIR = Path("/home/tiger/egoagent/identity")


def copy_identity(source_name: str, new_name: str = None, overwrite: bool = False):
    if not new_name:
        new_name = f"{source_name}_copy"

    source_path = IDENTITY_DIR / source_name
    target_path = IDENTITY_DIR / new_name

    if not source_path.is_dir():
        return f"Error: identity '{source_name}' not found at {source_path}"

    if target_path.exists():
        if overwrite:
            shutil.rmtree(target_path)
        else:
            return f"Error: identity '{new_name}' already exists at {target_path}. Use overwrite=true to replace it."

    # 复制整个目录
    shutil.copytree(source_path, target_path)

    # 更新 id.json 中的 name
    id_file = target_path / "id.json"
    if id_file.exists():
        id_data = json.loads(id_file.read_text(encoding="utf-8"))
        id_data["name"] = new_name
        id_file.write_text(json.dumps(id_data, ensure_ascii=False, indent=4), encoding="utf-8")

    # 清理 __pycache__
    for cache_dir in target_path.rglob("__pycache__"):
        shutil.rmtree(cache_dir)

    return f"Identity '{source_name}' copied to '{new_name}' at {target_path}"
