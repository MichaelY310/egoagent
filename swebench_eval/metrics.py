"""
SWE-bench 评估指标看板

功能：
- 解析 predictions.jsonl 和 SWE-bench 评估日志
- 计算 pass@k、通过率、耗时分布
- 生成统计报告

用法:
    python swebench_eval/metrics.py --predictions swebench_eval/predictions.jsonl
    python swebench_eval/metrics.py --predictions swebench_eval/predictions.jsonl --report report.json
    python swebench_eval/metrics.py --predictions swebench_eval/predictions.jsonl --compare other_predictions.jsonl
"""
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


def load_predictions(path: str) -> list:
    preds = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                preds.append(json.loads(line))
    return preds


def compute_basic_stats(predictions: list) -> dict:
    total = len(predictions)
    with_patch = sum(1 for p in predictions if p.get("model_patch"))
    without_patch = total - with_patch
    patch_sizes = [len(p.get("model_patch", "")) for p in predictions if p.get("model_patch")]
    elapsed_times = [p.get("_elapsed_seconds", 0) for p in predictions if p.get("_elapsed_seconds")]

    return {
        "total": total,
        "with_patch": with_patch,
        "without_patch": without_patch,
        "patch_rate": round(with_patch / total * 100, 1) if total > 0 else 0,
        "avg_patch_bytes": round(sum(patch_sizes) / len(patch_sizes), 1) if patch_sizes else 0,
        "median_patch_bytes": sorted(patch_sizes)[len(patch_sizes) // 2] if patch_sizes else 0,
        "min_patch_bytes": min(patch_sizes) if patch_sizes else 0,
        "max_patch_bytes": max(patch_sizes) if patch_sizes else 0,
        "avg_elapsed_seconds": round(sum(elapsed_times) / len(elapsed_times), 1) if elapsed_times else 0,
        "total_elapsed_seconds": round(sum(elapsed_times), 1),
        "total_elapsed_minutes": round(sum(elapsed_times) / 60, 1),
    }


def compute_time_distribution(predictions: list) -> dict:
    buckets = {
        "0-30s": 0,
        "30-60s": 0,
        "60-120s": 0,
        "120-300s": 0,
        "300s+": 0,
    }
    for p in predictions:
        t = p.get("_elapsed_seconds", 0)
        if t <= 30:
            buckets["0-30s"] += 1
        elif t <= 60:
            buckets["30-60s"] += 1
        elif t <= 120:
            buckets["60-120s"] += 1
        elif t <= 300:
            buckets["120-300s"] += 1
        else:
            buckets["300s+"] += 1
    return buckets


def compute_patch_size_distribution(predictions: list) -> dict:
    buckets = {
        "0 bytes (empty)": 0,
        "1-100 bytes": 0,
        "100-500 bytes": 0,
        "500-2000 bytes": 0,
        "2000+ bytes": 0,
    }
    for p in predictions:
        size = len(p.get("model_patch", ""))
        if size == 0:
            buckets["0 bytes (empty)"] += 1
        elif size <= 100:
            buckets["1-100 bytes"] += 1
        elif size <= 500:
            buckets["100-500 bytes"] += 1
        elif size <= 2000:
            buckets["500-2000 bytes"] += 1
        else:
            buckets["2000+ bytes"] += 1
    return buckets


def compute_error_summary(predictions: list) -> dict:
    errors = defaultdict(int)
    for p in predictions:
        err = p.get("_error", "")
        if err:
            errors[err[:100]] += 1
    return dict(errors)


def generate_report(predictions: list, label: str = "") -> dict:
    stats = compute_basic_stats(predictions)
    time_dist = compute_time_distribution(predictions)
    size_dist = compute_patch_size_distribution(predictions)
    errors = compute_error_summary(predictions)

    report = {
        "label": label,
        "basic_stats": stats,
        "time_distribution": time_dist,
        "patch_size_distribution": size_dist,
    }
    if errors:
        report["errors"] = errors

    return report


def print_report(report: dict):
    label = report.get("label", "")
    header = f"=== {label} ===" if label else "=== 评估报告 ==="
    print(header)

    stats = report["basic_stats"]
    print(f"\n基础统计:")
    print(f"  总数: {stats['total']}")
    print(f"  有 patch: {stats['with_patch']} ({stats['patch_rate']}%)")
    print(f"  无 patch: {stats['without_patch']}")
    print(f"  Patch 大小: 平均 {stats['avg_patch_bytes']}B, 中位 {stats['median_patch_bytes']}B")
    print(f"  耗时: 平均 {stats['avg_elapsed_seconds']}s, 总计 {stats['total_elapsed_minutes']}min")

    print(f"\n耗时分布:")
    for bucket, count in report["time_distribution"].items():
        bar = "█" * max(1, count)
        print(f"  {bucket:>12s}: {count:>4d} {bar}")

    print(f"\nPatch 大小分布:")
    for bucket, count in report["patch_size_distribution"].items():
        bar = "█" * max(1, count)
        print(f"  {bucket:>20s}: {count:>4d} {bar}")

    if "errors" in report:
        print(f"\n错误摘要:")
        for err, count in sorted(report["errors"].items(), key=lambda x: -x[1]):
            print(f"  [{count}x] {err}")


def compare_reports(report_a: dict, report_b: dict):
    print("=== 对比报告 ===")
    print(f"\n  {'指标':<25s} {'A':>10s} {'B':>10s} {'差异':>10s}")
    print(f"  {'-'*55}")

    stats_a = report_a["basic_stats"]
    stats_b = report_b["basic_stats"]

    rows = [
        ("总数", stats_a["total"], stats_b["total"]),
        ("有 patch", stats_a["with_patch"], stats_b["with_patch"]),
        ("patch 率", f"{stats_a['patch_rate']}%", f"{stats_b['patch_rate']}%"),
        ("平均 patch 大小", f"{stats_a['avg_patch_bytes']}B", f"{stats_b['avg_patch_bytes']}B"),
        ("平均耗时", f"{stats_a['avg_elapsed_seconds']}s", f"{stats_b['avg_elapsed_seconds']}s"),
        ("总耗时", f"{stats_a['total_elapsed_minutes']}min", f"{stats_b['total_elapsed_minutes']}min"),
    ]

    for name, a, b in rows:
        print(f"  {name:<25s} {str(a):>10s} {str(b):>10s}")


def main():
    parser = argparse.ArgumentParser(description="SWE-bench 评估指标看板")
    parser.add_argument("--predictions", type=str, required=True, help="predictions.jsonl 文件路径")
    parser.add_argument("--compare", type=str, default=None, help="对比的 predictions.jsonl 文件路径")
    parser.add_argument("--report", type=str, default=None, help="输出 JSON 报告文件路径")
    parser.add_argument("--label", type=str, default="", help="报告标签")
    args = parser.parse_args()

    predictions = load_predictions(args.predictions)
    if not predictions:
        print("Error: predictions 文件为空")
        return

    report = generate_report(predictions, args.label or args.predictions)
    print_report(report)

    if args.compare:
        compare_preds = load_predictions(args.compare)
        compare_report = generate_report(compare_preds, args.compare)
        print()
        print_report(compare_report)
        print()
        compare_reports(report, compare_report)

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n报告已写入: {args.report}")


if __name__ == "__main__":
    main()
