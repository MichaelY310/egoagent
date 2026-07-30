"""
gate_decision.py — 门控决策：评估新分数，决定接受/拒绝/回滚
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx: dict) -> dict:
    from self_evolution.engine import rollback, record_attempt

    results = ctx.get("eval_tasks_results", [])
    current_score = ctx.get("current_score", 0.0)
    snap_id = ctx.get("snap_id", "")
    target_identity = ctx.get("target_identity", "dante")
    iteration = ctx.get("iteration", 0)
    max_iterations = ctx.get("max_iterations", 3)
    action_desc = ctx.get("action_desc", "")
    gradient = ctx.get("gradient", "")
    report = ctx.get("report", {})

    # 计算新分数
    scores = []
    for r in results:
        if isinstance(r, (int, float)):
            scores.append(float(r))
        elif isinstance(r, str):
            nums = re.findall(r"[01]?\.\d+|1\.0|0\.0", r)
            if nums:
                scores.append(max(0.0, min(1.0, float(nums[0]))))
            else:
                scores.append(0.5)
        else:
            scores.append(0.5)

    new_score = sum(scores) / len(scores) if scores else 0.0

    # 门控逻辑（百分制对比）
    threshold = 5.0
    improvement = (new_score - current_score) * 100

    if improvement >= threshold:
        decision = "accept"
    elif improvement >= 0:
        decision = "accept"  # 微小改进也接受
    elif improvement > -threshold:
        decision = "reject"
    else:
        decision = "rollback"

    # 执行回滚
    if decision in ("reject", "rollback"):
        rollback(target_identity, snap_id)

    # 更新分数（仅接受时）
    if decision == "accept":
        current_score = new_score

    # 更新报告
    iter_report = {
        "iteration": iteration + 1,
        "score_before": ctx.get("current_score", 0.0),
        "score_after": new_score,
        "action": action_desc,
        "decision": decision,
    }
    if "iterations" not in report:
        report["iterations"] = []
    report["iterations"].append(iter_report)

    if decision == "accept":
        report["total_accepted"] = report.get("total_accepted", 0) + 1
    elif decision == "reject":
        report["total_rejected"] = report.get("total_rejected", 0) + 1
    else:
        report["total_rollbacks"] = report.get("total_rollbacks", 0) + 1

    # 记录到归档
    record_attempt({
        "target": f"{ctx.get('target_harness', 'unknown')}/{target_identity}",
        "action": action_desc,
        "diff": gradient[:500] if gradient else "",
        "score_before": ctx.get("current_score", 0.0),
        "score_after": new_score,
        "accepted": decision == "accept",
    })

    # 递增迭代
    iteration += 1

    return {
        "new_score": new_score,
        "decision": decision,
        "current_score": current_score,
        "iteration": iteration,
        "report": report,
    }
