"""Run the preregistered P6 EgoAgent/profile and upstream Codex comparison."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.env_config import load_local_env
from task_bench.engine import TaskBenchError, TaskBenchManager

from experiments.product_code_agent_acceptance.run_matrix import analyze, wait_for_run


LANES = [
    ("ego_fast", "ego_flow", "code_agent_fast"),
    ("ego_auto", "ego_flow", "code_agent_auto"),
    ("ego_long", "ego_flow", "code_agent_long"),
    ("ego_team", "ego_flow", "code_agent_team"),
    ("ego_core", "ego_flow", "product_core_code_agent"),
    ("original_codex", "codex_cli", "original_codex"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", default=["product_compare_small", "product_compare_large"])
    parser.add_argument("--lanes", nargs="+", choices=[lane[0] for lane in LANES])
    parser.add_argument("--label", default="product_comparison_p6_r1")
    args = parser.parse_args()
    selected = [lane for lane in LANES if not args.lanes or lane[0] in args.lanes]

    loaded = load_local_env(ROOT)
    print("Loaded provider variable names:", ", ".join(loaded) if loaded else "already present", flush=True)
    manager = TaskBenchManager(ROOT)
    output_dir = ROOT / "experiments" / "product_code_agent_acceptance" / "results" / (
        time.strftime("%Y%m%d_%H%M%S") + "_" + args.label
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "ego.product-comparison.v1",
        "created_at": time.time(),
        "tasks": args.tasks,
        "lanes": [lane[0] for lane in selected],
        "caveat": "Cross-provider product comparison; not a same-model causal ablation.",
        "runs": [],
    }
    for task_id in args.tasks:
        for lane_name, runner, flow in selected:
            print(f"START task={task_id} lane={lane_name}", flush=True)
            try:
                payload = {"task_id": task_id, "runner": runner, "debug_mode": "auto"}
                if runner == "ego_flow":
                    payload.update({"harness": flow, "identity": "adaptive_deepseek_coder"})
                created = manager.start(payload)
                state = wait_for_run(manager, created["id"])
                summary = analyze(state)
                summary["lane"] = lane_name
                summary["runner"] = runner
                summary["runner_metadata"] = state.get("runner") or {}
            except (TaskBenchError, OSError, ValueError) as error:
                summary = {
                    "run_id": None, "task_id": task_id, "lane": lane_name, "runner": runner,
                    "flow": flow, "status": "error", "score": None, "stats": {},
                    "error": f"{type(error).__name__}: {error}",
                }
            report["runs"].append(summary)
            (output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"DONE task={task_id} lane={lane_name} status={summary['status']} "
                f"score={summary.get('score')} error={summary.get('error') or '-'}",
                flush=True,
            )
    report_path = output_dir / "report.json"
    print(f"REPORT {report_path}", flush=True)
    return 0 if all(run["status"] == "passed" for run in report["runs"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
