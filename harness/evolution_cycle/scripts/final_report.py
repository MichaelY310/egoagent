"""
final_report.py — 生成最终进化报告并持久化
"""
import json
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx: dict) -> dict:
    from self_evolution.engine import DATA_DIR, _save_json

    report = ctx.get("report", {})
    baseline_score = ctx.get("baseline_score", 0.0)
    current_score = ctx.get("current_score", 0.0)

    report["initial_score"] = baseline_score
    report["final_score"] = current_score

    # 持久化报告
    report_file = DATA_DIR / f"report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    _save_json(report_file, report)

    return {
        "report": report,
    }
