"""Run low-leakage self-evolution probes with the configured real model.

The task prompts describe recurring operational pressure but never tell the
model which mutation tool or capability pack to choose. Each case uses a fresh
temporary clone of Dante and deletes only that namespaced clone plus resources
generated from it after recording the report.
"""

from __future__ import annotations

import json
import argparse
import os
import shutil
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.env_config import load_local_env
from task_bench.engine import TERMINAL_STATES, TaskBenchManager


load_local_env(PROJECT_ROOT)
for _name in list(os.environ):
    if "proxy" in _name.lower():
        os.environ.pop(_name, None)
RUN_ROOT = Path(__file__).resolve().parent / "_runs"


def _clone_identity(name: str) -> Path:
    if not name.startswith("deepseek_probe_"):
        raise ValueError("probe identity must use the deepseek_probe_ prefix")
    source = PROJECT_ROOT / "identity" / "dante"
    target = PROJECT_ROOT / "identity" / name
    shutil.copytree(source, target)
    id_path = target / "id.json"
    data = json.loads(id_path.read_text(encoding="utf-8"))
    data["name"] = name
    data["description"] = str(data.get("description", "")) + " This is an isolated Task Bench evolution probe."
    id_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _safe_remove(path: Path, allowed_names: set[str], allowed_root: Path) -> None:
    resolved = path.resolve()
    if resolved.name not in allowed_names or resolved.parent != allowed_root.resolve():
        raise RuntimeError(f"refusing cleanup outside probe namespace: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)


def _wait(manager: TaskBenchManager, run_id: str, timeout: float = 360) -> dict:
    deadline = time.monotonic() + timeout
    state = manager.get(run_id)
    while state.get("status") not in TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.25)
        state = manager.get(run_id)
    if state.get("status") not in TERMINAL_STATES:
        try:
            manager.control(run_id, "stop")
        except Exception:
            pass
        raise TimeoutError(f"task {run_id} did not finish within {timeout}s")
    return state


def _tool_trace(state: dict) -> list[dict]:
    items = []
    for trace in state.get("node_traces", []):
        for call in trace.get("tools", []):
            items.append({
                "node": trace.get("node_id"),
                "name": call.get("name"),
                "arguments": call.get("arguments"),
                "result": str(call.get("result", ""))[:1200],
                "blocked": bool(call.get("blocked")),
            })
    return items


def _summarize(state: dict, before_skills: set[str], identity_dir: Path) -> dict:
    after_skills = {path.name for path in (identity_dir / "ego" / "skills").iterdir() if path.is_dir()}
    final_response = "".join(
        str(item.get("text", "")) for item in state.get("outputs", []) if item.get("type") == "text"
    )
    return {
        "run_id": state.get("id"),
        "task_id": state.get("task_id"),
        "status": state.get("status"),
        "error": state.get("error"),
        "score": (state.get("evaluation") or {}).get("score"),
        "checks": (state.get("evaluation") or {}).get("checks", []),
        "new_skills": sorted(after_skills - before_skills),
        "mutations": state.get("mutations", {}),
        "evolution_events": state.get("evolution_events", []),
        "tools": _tool_trace(state),
        "stats": state.get("stats", {}),
        "final_response": final_response[-5000:],
    }


def run_case(task_id: str, stamp: str, index: int) -> dict:
    identity_name = f"deepseek_probe_{stamp}_{index}"
    identity_dir = _clone_identity(identity_name)
    worker_name = f"{identity_name}_search_worker"
    harness_name = f"{identity_name}_result_only_search"
    allowed_identity_names = {identity_name, worker_name}
    allowed_harness_names = {harness_name}
    state = None
    try:
        before_skills = {path.name for path in (identity_dir / "ego" / "skills").iterdir() if path.is_dir()}
        manager = TaskBenchManager(
            PROJECT_ROOT,
            runs_dir=RUN_ROOT / stamp / "task_runs",
        )
        created = manager.start({
            "task_id": task_id,
            "harness": "react_single",
            "identity": identity_name,
            "debug_mode": "auto",
        })
        state = _wait(manager, created["id"])
        return _summarize(state, before_skills, identity_dir)
    finally:
        mutations = (state or {}).get("mutations", {})
        allowed_identity_names.update(
            name for name in mutations.get("identity_created", [])
            if isinstance(name, str) and name
        )
        allowed_harness_names.update(
            name for name in mutations.get("harness_created", [])
            if isinstance(name, str) and name
        )
        for name in allowed_harness_names:
            _safe_remove(PROJECT_ROOT / "harness" / name, allowed_harness_names, PROJECT_ROOT / "harness")
        for name in allowed_identity_names:
            _safe_remove(PROJECT_ROOT / "identity" / name, allowed_identity_names, PROJECT_ROOT / "identity")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task_ids",
        nargs="*",
        default=[
            "latent_paper_recall",
            "latent_delegated_search",
            "latent_skill_extraction",
        ],
        help="Task Bench task ids to run (defaults to the three baseline probes).",
    )
    args = parser.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    destination = RUN_ROOT / stamp
    destination.mkdir(parents=True, exist_ok=False)
    report = {
        "version": 1,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "method": {
            "task_specific_evolution_instruction": False,
            "generic_evolution_governance": True,
            "tool_interface_visible": True,
            "deterministic_capability_analyzer_available": True,
            "notes": "Prompts expose recurring cost/quality pressure but do not name mutation tools, packs, Skills, sub-Agents, or Harness edits.",
        },
        "cases": [],
    }
    for index, task_id in enumerate(args.task_ids, start=1):
        print(f"[{index}/{len(args.task_ids)}] {task_id}", flush=True)
        try:
            report["cases"].append(run_case(task_id, stamp, index))
        except Exception as error:
            report["cases"].append({"task_id": task_id, "status": "runner_error", "error": str(error)})
    report_path = destination / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path, flush=True)
    return 0 if all(case.get("status") in {"passed", "failed"} for case in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
