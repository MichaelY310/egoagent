"""Run reproducible DeepSeek coding tasks through the Codex-style Flow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_factory import AgentFactory
from harness import Harness
from llm.env_config import load_local_env
from pipeline_engine import PipelineRunner


TASKS = {
    "off_by_one": (
        "The moving_average implementation has an off-by-one defect. Reproduce it with the existing tests, "
        "make the smallest correct fix, and run the full test suite. Do not only explain the patch.",
        "python -m unittest discover -s tests -v",
    ),
    "duration_parser": (
        "parse_duration handles one duration component but fails valid composite durations such as 1h30m5s. "
        "Inspect the implementation and tests, implement a dependency-free fix while preserving malformed-input errors, "
        "then run the complete test suite.",
        "python -m unittest discover -s tests -v",
    ),
}


def run_task(
    name: str,
    *,
    flow_name: str = "codex_flow",
    identity_name: str = "codex_operator",
    experiment_name: str = "codex_flow",
) -> dict:
    prompt, verification_command = TASKS[name]
    source = ROOT / "experiments" / "codex_flow" / "fixtures" / name
    run_id = f"{int(time.time())}-{name}-{uuid.uuid4().hex[:6]}"
    workspace = ROOT / "experiments" / experiment_name / "runs" / run_id
    shutil.copytree(source, workspace)
    factory = AgentFactory()
    flow_dir = ROOT / "harness" / flow_name
    flow_config = json.loads((flow_dir / "config.json").read_text(encoding="utf-8"))
    agents = {
        slot: factory.create(ROOT / "identity" / identity_name, name=slot, workspace=workspace)
        for slot in (flow_config.get("slots") or {})
    }
    harness = Harness(flow_dir, agents=agents, workspace=workspace)
    harness._non_interactive = True
    # This controlled fixture is the explicit approval boundary for the live
    # experiment. The shipped Flow remains ask-by-default for real users.
    harness.config["pipeline"]["permissions"] = {
        "defaults": {"read": "allow", "write": "allow", "process": "allow", "network": "deny", "mutation": "deny", "secret": "deny"}
    }
    review = harness.config["pipeline"]["nodes"].get("permissions")
    if isinstance(review, dict):
        review["default_permission"] = "allow"
        review["policies"] = []
    user_message = {"role": "user", "content": prompt}
    harness.session.record(user_message)
    harness.session.record_full(user_message.copy())
    started = time.time()
    error = None
    result = None
    try:
        result = PipelineRunner(harness).run()
    except Exception as caught:
        error = f"{type(caught).__name__}: {caught}"
    verification = subprocess.run(
        verification_command,
        shell=True,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = {
        "task": name,
        "flow": flow_name,
        "identity": identity_name,
        "run_id": run_id,
        "workspace": str(workspace.relative_to(ROOT)),
        "prompt": prompt,
        "elapsed_seconds": round(time.time() - started, 3),
        "error": error,
        "result": result.result if result is not None else None,
        "stats": vars(result.stats) if result is not None else None,
        "trajectory": result.data.get("_trajectory", []) if result is not None else [],
        "independent_verification": {
            "command": verification_command,
            "exit_code": verification.returncode,
            "stdout": verification.stdout,
            "stderr": verification.stderr,
            "passed": verification.returncode == 0,
        },
        "session_dir": str(harness.session.save_dir),
    }
    output = ROOT / "experiments" / experiment_name / "results" / f"{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="*", choices=sorted(TASKS), default=list(TASKS))
    args = parser.parse_args()
    load_local_env(ROOT)
    results = [run_task(name) for name in (args.tasks or list(TASKS))]
    summary = [{
        "task": item["task"],
        "error": item["error"],
        "passed": item["independent_verification"]["passed"],
        "model_calls": (item["stats"] or {}).get("model_calls"),
        "tool_calls": (item["stats"] or {}).get("tool_calls"),
        "trajectory_actions": [step.get("action") for step in item["trajectory"]],
        "workspace": item["workspace"],
    } for item in results]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(item["error"] is None and item["independent_verification"]["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
