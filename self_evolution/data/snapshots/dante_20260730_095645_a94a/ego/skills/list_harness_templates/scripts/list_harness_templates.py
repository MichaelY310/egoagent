"""
列出所有可用的 harness 模板目录，返回结构化概览。
"""
import json
from pathlib import Path


def list_harness_templates(verbose: bool = False):
    from config import CONFIG

    harness_root = Path(CONFIG.get("harness_template_repository", ""))
    if not harness_root.exists():
        # fallback: 相对于项目根目录
        harness_root = Path(__file__).resolve().parents[6] / "harness"
    if not harness_root.exists():
        return "Error: harness template directory not found."

    templates = []
    for d in sorted(harness_root.iterdir()):
        config_path = d / "config.json"
        if not d.is_dir() or not config_path.exists():
            continue
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        entry = {
            "name": cfg.get("name", d.name),
            "path": str(d),
            "description": cfg.get("description", ""),
            "slots": {},
            "return_mode": cfg.get("return_mode", "all"),
        }

        for slot_name, slot_def in cfg.get("slots", {}).items():
            entry["slots"][slot_name] = slot_def.get("description", "")

        if verbose:
            pipeline = cfg.get("pipeline", {})
            entry["pipeline_start"] = pipeline.get("start", "")
            entry["max_steps"] = pipeline.get("max_steps", 100)
            entry["nodes"] = list(pipeline.get("nodes", {}).keys())
            entry["prompts"] = list(cfg.get("prompts", {}).keys())

        templates.append(entry)

    if not templates:
        return "No harness templates found."

    lines = [f"共找到 {len(templates)} 个 harness 模板:\n"]
    for t in templates:
        lines.append(f"━━━ {t['name']} ━━━")
        lines.append(f"  路径: {t['path']}")
        lines.append(f"  描述: {t['description']}")
        slots_str = ", ".join(f"{k}({v})" for k, v in t["slots"].items())
        lines.append(f"  Slots: {slots_str}")
        lines.append(f"  Return mode: {t['return_mode']}")
        if verbose:
            lines.append(f"  Pipeline start: {t['pipeline_start']}")
            lines.append(f"  Max steps: {t['max_steps']}")
            lines.append(f"  Nodes: {', '.join(t['nodes'])}")
            if t["prompts"]:
                lines.append(f"  Prompts: {', '.join(t['prompts'])}")
        lines.append("")

    return "\n".join(lines)
