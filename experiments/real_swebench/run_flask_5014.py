"""Run DeepSeek V4 Flash on one real SWE-bench Verified Flask issue.

The external repository must already be checked out at the instance base
commit and have the official *test patch* applied.  The script never reads the
gold solution patch.  All writes and commands are confined to that external
workspace by EgoAgent's task permission policy.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
WORKSPACE = ROOT / "experiments" / "external" / "flask-7ee9ceb71e868944a46e1ff00b506772a53a4f1d"
VENV_PYTHON = ROOT / "experiments" / "external" / "flask-swe5014-venv" / "Scripts" / "python.exe"
RUN_ROOT = Path(__file__).resolve().parent / "_runs"


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _test(command: list[str]) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-20_000:],
        "stderr": completed.stderr[-20_000:],
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    if not WORKSPACE.is_dir() or not VENV_PYTHON.is_file():
        raise SystemExit("Flask workspace or local venv is missing; see experiments/real_swebench/README.md")

    from agent import Agent
    from harness import Harness
    from llm.env_config import load_local_env
    from permissions import RuntimePolicy
    from pipeline_engine import PipelineRunner

    load_local_env(ROOT)
    prompt = f"""Resolve this real GitHub issue in the current Flask repository.

Issue: Require a non-empty name for Blueprints

Things do not work correctly if a Blueprint is given an empty name. It would
be helpful if a ValueError was raised when trying to do that.

The official reproduction test is already present at
tests/test_blueprints.py::test_empty_name_not_allowed. Inspect the code, make
the smallest coherent production-code fix, and run that test. Do not edit the
test. The compatible test command for this Windows environment is:

{VENV_PYTHON} -m pytest tests/test_blueprints.py::test_empty_name_not_allowed -q --override-ini filterwarnings=ignore

After the focused test passes, run nearby Blueprint tests if budget permits.
"""

    agent = Agent(ROOT / "identity" / "coder", name="coder", workspace=WORKSPACE)
    harness = Harness(
        ROOT / "harness" / "bounded_coder_worker",
        agents={"coder": agent},
        workspace=WORKSPACE,
    )
    harness._non_interactive = True
    harness.session.record({"role": "user", "name": "swe_bench", "content": prompt})
    harness.session.record_full({"role": "user", "name": "swe_bench", "content": prompt})
    events: list[dict] = []
    started = time.monotonic()
    runner = PipelineRunner(
        harness,
        on_output=lambda event, data: events.append({"event": event, "data": data}),
        get_input=lambda: None,
        is_running=lambda: True,
        permission_policy=RuntimePolicy.for_task(WORKSPACE, network="disabled"),
        initial_data={
            "task": {
                "id": "pallets__flask-5014",
                "prompt": prompt,
                "workspace": str(WORKSPACE),
            }
        },
    )
    error = None
    context = None
    try:
        context = runner.run()
    except Exception as exc:  # preserve a failed research episode as evidence
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        harness.session.save()

    focused = _test(
        [
            str(VENV_PYTHON), "-m", "pytest",
            "tests/test_blueprints.py::test_empty_name_not_allowed", "-q",
            "--override-ini", "filterwarnings=ignore",
        ]
    )
    nearby = _test(
        [
            str(VENV_PYTHON), "-m", "pytest", "tests/test_blueprints.py", "-q",
            "--override-ini", "filterwarnings=ignore",
        ]
    ) if focused["exit_code"] == 0 else None
    diff = subprocess.run(
        ["git", "diff", "--", "src", "tests"], cwd=WORKSPACE,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    ).stdout
    test_changed = "tests/test_blueprints.py" in diff and "+def test_empty_name_not_allowed" not in diff
    # The official test patch is expected and was installed before this run;
    # flag any additional test changes for manual inspection.
    report = {
        "format": "ego.swebench-real-smoke.v1",
        "instance_id": "pallets__flask-5014",
        "repo": "pallets/flask",
        "base_commit": "7ee9ceb71e868944a46e1ff00b506772a53a4f1d",
        "model": "deepseek-v4-flash",
        "harness": "bounded_coder_worker",
        "identity": "coder",
        "gold_patch_exposed_to_agent": False,
        "official_test_patch_installed_before_run": True,
        "runtime_error": error,
        "runner_result": context.result if context else None,
        "stats": context.stats.as_dict() if context else {},
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "focused_test": focused,
        "nearby_blueprint_tests": nearby,
        "resolved": focused["exit_code"] == 0 and error is None,
        "possible_additional_test_edit": test_changed,
        "diff": diff,
        "events": events,
        "session_dir": str(harness.session.save_dir.resolve()),
    }
    destination = RUN_ROOT / "pallets__flask-5014_v4.json"
    _write_json(destination, report)
    print(destination)
    print(json.dumps({
        "resolved": report["resolved"],
        "runtime_error": error,
        "focused_exit": focused["exit_code"],
        "nearby_exit": None if nearby is None else nearby["exit_code"],
        "stats": report["stats"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["resolved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
