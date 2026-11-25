"""Run the preregistered Identity -> EGO -> Superego matched pilot."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.product_code_agent_acceptance.run_matrix import analyze, wait_for_run
from llm.env_config import load_local_env
from task_bench.engine import TaskBenchError, TaskBenchManager


DEFAULT_IDENTITIES = [
    "experiment_identity_neutral",
    "experiment_identity_id",
    "experiment_identity_ego",
    "experiment_identity_full",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identities", nargs="+", default=DEFAULT_IDENTITIES)
    parser.add_argument("--task", default="product_identity_confidentiality_repair")
    parser.add_argument("--flow", default="product_core_code_agent")
    parser.add_argument("--label", default="identity_factorial_r1")
    args = parser.parse_args()

    loaded = load_local_env(ROOT)
    print("Loaded provider variable names:", ", ".join(loaded) if loaded else "already present", flush=True)
    manager = TaskBenchManager(ROOT)
    output_dir = ROOT / "experiments" / "product_code_agent_acceptance" / "results" / (
        time.strftime("%Y%m%d_%H%M%S") + "_" + args.label
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "ego.identity-factorial.v1",
        "created_at": time.time(),
        "task": args.task,
        "flow": args.flow,
        "identities": args.identities,
        "runs": [],
    }

    for identity in args.identities:
        print(f"START identity={identity}", flush=True)
        try:
            created = manager.start({
                "task_id": args.task,
                "harness": args.flow,
                "identity": identity,
                "slot_bindings": {"agent": identity, "governor": identity},
                "debug_mode": "auto",
            })
            state = wait_for_run(manager, created["id"])
            summary = analyze(state)
            summary["identity"] = identity
            summary["evaluation"] = state.get("evaluation") or {}
            summary["messages"] = state.get("messages") or []
        except (TaskBenchError, OSError, ValueError) as error:
            summary = {
                "identity": identity,
                "status": "error",
                "score": None,
                "error": f"{type(error).__name__}: {error}",
            }
        report["runs"].append(summary)
        (output_dir / f"{identity}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"DONE identity={identity} status={summary.get('status')} "
            f"score={summary.get('score')} error={summary.get('error') or '-'}",
            flush=True,
        )

    print(f"REPORT {output_dir / 'report.json'}", flush=True)
    # A failed behavioral arm is a scientific result, not a runner error.
    return 0 if all(item.get("status") in {"passed", "failed"} for item in report["runs"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
