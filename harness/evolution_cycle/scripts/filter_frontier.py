"""
filter_frontier.py — 筛选前沿任务（难度 0.3-0.8 区域）
"""


def run(ctx: dict) -> dict:
    task_pool = ctx.get("task_pool", [])
    iteration = ctx.get("iteration", 0)
    max_iterations = ctx.get("max_iterations", 3)

    # 筛选有 difficulty 标记的前沿任务
    frontier = []
    for t in task_pool:
        d = t.get("difficulty", -1)
        if 0.3 <= d <= 0.8:
            frontier.append(t)

    # 如果没有标记过 difficulty 的任务，取 3 个
    if not frontier:
        # 按轮次偏移取不同的子集
        start = (iteration * 3) % max(len(task_pool), 1)
        frontier = task_pool[start:start + 3]
        if not frontier:
            frontier = task_pool[:3]

    # 转为描述字符串列表（供循环使用）
    frontier_tasks = [t["description"] if isinstance(t, dict) else str(t) for t in frontier[:3]]

    return {
        "frontier_tasks": frontier_tasks,
    }
