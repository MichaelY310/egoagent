"""复制一个现有的 harness 模板到新名称，自动更新 config.json 中的 name 字段。"""
import shutil
import json
from pathlib import Path


def copy_harness(source_name: str, new_name: str, overwrite: bool = False):
    from config import CONFIG

    repo = Path(CONFIG["harness_template_repository"])
    source_path = repo / source_name
    target_path = repo / new_name

    if not source_path.exists():
        return f"Error: source harness '{source_name}' not found at {source_path}"

    if target_path.exists():
        if overwrite:
            shutil.rmtree(target_path)
        else:
            return f"Error: harness '{new_name}' already exists at {target_path}. Use overwrite=true to replace it."

    # 复制整个目录
    shutil.copytree(source_path, target_path)

    # 更新 config.json 中的 name 字段
    config_file = target_path / "config.json"
    if config_file.exists():
        config = json.load(open(config_file, encoding="utf-8"))
        config["name"] = new_name
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    # 清理 __pycache__
    pycache = target_path / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)

    return f"Harness '{source_name}' copied to '{new_name}' at {target_path}"
