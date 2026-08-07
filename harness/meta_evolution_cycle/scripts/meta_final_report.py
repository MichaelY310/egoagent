"""meta_final_report: Assemble and record the final meta-evolution report."""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()

    meta_report = ctx.get("meta_report", {})
    meta_report["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta_report["old_performance"] = ctx.get("old_performance", {})
    meta_report["new_performance"] = ctx.get("new_performance", {})
    meta_report["meta_gradient"] = ctx.get("meta_gradient", {})
    meta_report["decision"] = ctx.get("meta_decision", "unknown")
    meta_report["final_strategy"] = ctx.get("current_strategy", {})

    # Record to archive
    engine._record_meta_archive(meta_report)

    return {
        "meta_report": meta_report,
    }
