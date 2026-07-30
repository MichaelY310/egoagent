"""
collect_failures.py — 从测试结果中收集失败的任务
"""
import re


def run(ctx: dict) -> dict:
    frontier_tasks = ctx.get("frontier_tasks", [])
    results = ctx.get("frontier_tasks_results", [])

    failed_tasks = []
    test_results = []

    for i, (task, result) in enumerate(zip(frontier_tasks, results)):
        # 解析分数
        score = 0.5
        if isinstance(result, (int, float)):
            score = float(result)
        elif isinstance(result, str):
            nums = re.findall(r"[01]?\.\d+|1\.0|0\.0", result)
            if nums:
                score = max(0.0, min(1.0, float(nums[0])))

        test_results.append({"task": task, "score": score})
        if score < 0.5:
            failed_tasks.append(task)

    # 如果没有明确失败的，取分数最低的
    if not failed_tasks and test_results:
        sorted_results = sorted(test_results, key=lambda x: x["score"])
        failed_tasks = [sorted_results[0]["task"]]

    return {
        "failed_tasks": failed_tasks,
        "test_results": test_results,
    }
