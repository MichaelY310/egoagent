"""Run a real DeepSeek coding task through the DeepSeek Harness replica Flow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.codex_flow.run_deepseek_tasks import TASKS, run_task
from llm.env_config import load_local_env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=sorted(TASKS), default="off_by_one", nargs="?")
    args = parser.parse_args()
    load_local_env(ROOT)
    result = run_task(
        args.task,
        flow_name="deepseek_harness_replica",
        identity_name="deepseek_operator",
        experiment_name="deepseek_harness_flow",
    )
    print(json.dumps({
        "task": result["task"],
        "flow": result["flow"],
        "workspace": result["workspace"],
        "session_dir": result["session_dir"],
        "error": result["error"],
        "passed": result["independent_verification"]["passed"],
        "stats": result["stats"],
        "actions": [item.get("action") for item in result["trajectory"]],
    }, ensure_ascii=False, indent=2, default=str))
    return 0 if result["error"] is None and result["independent_verification"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
