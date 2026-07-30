"""
init_evolution.py — 初始化进化循环
加载或生成任务池，准备评估任务列表
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx: dict) -> dict:
    from self_evolution.engine import get_task_pool, _generate_candidate_tasks, _save_json, TASK_POOL_FILE

    target_harness = ctx.get("target_harness", "react_single")
    target_identity = ctx.get("target_identity", "dante")
    max_iterations = ctx.get("max_iterations", 3)

    # 加载或生成任务池
    task_pool = get_task_pool()
    if not task_pool:
        task_pool = _generate_candidate_tasks(target_harness, target_identity)
        _save_json(TASK_POOL_FILE, task_pool)

    # 取前 5 个作为评估任务
    eval_tasks = [t["description"] for t in task_pool[:5]]

    # 初始化报告
    report = {
        "target_harness": target_harness,
        "target_identity": target_identity,
        "max_iterations": max_iterations,
        "iterations": [],
        "initial_score": 0.0,
        "final_score": 0.0,
        "total_accepted": 0,
        "total_rejected": 0,
        "total_rollbacks": 0,
    }

    return {
        "task_pool": task_pool,
        "eval_tasks": eval_tasks,
        "report": report,
    }
