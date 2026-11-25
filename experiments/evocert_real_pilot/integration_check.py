"""Run one non-counted validation cell to validate the remote installation."""

from __future__ import annotations

import json
import time

from experiments.evocert_real_pilot.run import FAMILIES, RUN_ROOT, _run_task


def main() -> int:
    family = FAMILIES["logq"]
    stamp = f"integration_{time.strftime('%Y%m%d_%H%M%S')}"
    root = RUN_ROOT / stamp
    result = _run_task(
        family.validation_task,
        identity="coder",
        harness="bounded_coder_worker",
        variant="none",
        family=family,
        protocol={"title": ""},
        task_dir=root / "task_specs",
        runs_dir=root / "task_runs",
    )
    summary = {
        key: result.get(key)
        for key in ("task_id", "run_id", "status", "runtime_error", "success", "tokens", "elapsed_seconds")
    }
    summary["verifier"] = result.get("verifier")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not result.get("runtime_error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
