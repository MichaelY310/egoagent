"""
compute_score.py — 从循环结果计算平均分数
"""
import re


def run(ctx: dict) -> dict:
    results = ctx.get("eval_tasks_results", [])

    scores = []
    for r in results:
        # r 可能是 LLM 返回的评分文本
        if isinstance(r, (int, float)):
            scores.append(float(r))
        elif isinstance(r, str):
            # 尝试提取浮点数
            nums = re.findall(r"[01]?\.\d+|1\.0|0\.0", r)
            if nums:
                scores.append(max(0.0, min(1.0, float(nums[0]))))
            else:
                try:
                    scores.append(float(r.strip().split()[0]))
                except (ValueError, IndexError):
                    scores.append(0.5)
        else:
            scores.append(0.5)

    avg = sum(scores) / len(scores) if scores else 0.0

    return {
        "baseline_score": avg,
        "current_score": avg,
    }
