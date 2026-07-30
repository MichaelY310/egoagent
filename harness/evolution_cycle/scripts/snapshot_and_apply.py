"""
snapshot_and_apply.py — 创建快照并应用文本梯度修改
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx: dict) -> dict:
    from self_evolution.engine import snapshot, apply_gradient, retrieve_principles, _save_json, PRINCIPLES_FILE, _load_json

    target_identity = ctx.get("target_identity", "dante")
    gradient = ctx.get("gradient", "")
    new_principles = ctx.get("new_principles", [])

    # 创建快照
    snap_id = snapshot(target_identity)
    action_desc = ""

    # 保存新原则到原则库
    if isinstance(new_principles, list) and new_principles:
        import uuid
        principles = _load_json(PRINCIPLES_FILE)
        for p in new_principles:
            if isinstance(p, dict) and "description" in p:
                principles.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": p.get("type", "guiding"),
                    "description": p["description"],
                    "score": 0.5,
                    "usage_count": 0,
                    "success_count": 0,
                })
        _save_json(PRINCIPLES_FILE, principles)

    # 应用梯度
    if gradient and "[LLM_ERROR]" not in gradient and gradient.strip():
        result = apply_gradient(target_identity, "description", gradient)
        if result.get("success"):
            action_desc = f"Updated description via text gradient"
        else:
            action_desc = "Gradient application failed"
    else:
        # 无梯度时用原则增强
        principles = retrieve_principles("general improvement")
        if principles:
            principle_text = "; ".join(p["description"] for p in principles[:2])
            result = apply_gradient(target_identity, "description",
                                    f"Incorporate these principles: {principle_text}")
            action_desc = f"Enhanced with principles: {principle_text[:80]}"
        else:
            action_desc = "No modifications applied (no gradient or principles)"

    return {
        "snap_id": snap_id,
        "action_desc": action_desc,
    }
