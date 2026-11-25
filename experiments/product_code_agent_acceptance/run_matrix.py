"""Run reproducible EgoAgent product acceptance tasks with real model calls.

The script never reads or prints a key directly. ``load_local_env`` populates
the provider environment before Agent construction, and Task Bench stores the
exact Flow version, isolated workspace, deterministic checks and full trace.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.env_config import load_local_env
from task_bench.engine import TaskBenchError, TaskBenchManager


DEFAULT_FLOWS = [
    "product_core_code_agent",
    "product_adaptive_no_evolution",
    "product_adaptive_code_agent",
]
DEFAULT_TASKS = ["product_release_guard_long_horizon"]


def native_trajectory_evidence(run_id: str) -> dict:
    """Summarize durable native traces without embedding huge event payloads."""

    run_dir = ROOT / ".egoagent" / "task_runs" / str(run_id)
    paths = sorted((run_dir / "session").glob("*/trajectory.jsonl"))
    event_counts: Counter[str] = Counter()
    component_subflows: Counter[str] = Counter()
    autonomous_subagents: Counter[str] = Counter()
    evolution_reviews = []
    context_changes = []
    for path in paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except ValueError:
                continue
            data = event.get("data") or {}
            name = str(data.get("event") or event.get("type") or "")
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
            event_counts[name] += 1
            if name == "subagent_spawned":
                child = str(payload.get("child_harness") or "unknown")
                if payload.get("purpose") == "subdag_component":
                    component_subflows[child] += 1
                else:
                    autonomous_subagents[child] += 1
            if name == "subagent_completed" and payload.get("child_harness") == "component_capability_evolver":
                result = payload.get("result") or {}
                outputs = result.get("component_outputs") or {}
                evolution_reviews.append({
                    "evolved": bool(outputs.get("evolved")),
                    "decision": outputs.get("decision") or {},
                    "verification_decision": outputs.get("verification_decision") or {},
                })
            if name in {
                "conversation_applied", "context_compacted", "tool_results_pruned",
                "context.tool_preamble_compacted",
            }:
                context_changes.append({
                    "event": name,
                    "mode": payload.get("mode"),
                    "before_tokens_estimated": payload.get("before_tokens_estimated"),
                    "after_tokens_estimated": payload.get("after_tokens_estimated"),
                    "saved_tokens_estimated": payload.get("saved_tokens_estimated"),
                    "before_chars": payload.get("before_chars"),
                    "after_chars": payload.get("after_chars"),
                    "saved_chars": payload.get("saved_chars"),
                })
    return {
        "files": [str(path.resolve()) for path in paths],
        "event_counts": dict(event_counts),
        "component_subflows": dict(component_subflows),
        "autonomous_subagents": dict(autonomous_subagents),
        "evolution_reviews": evolution_reviews,
        "context_changes": context_changes,
    }


def analyze(run: dict) -> dict:
    traces = run.get("node_traces") or []
    events = run.get("events") or []
    tool_names = [
        str(call.get("name") or "").split(":")[-1]
        for trace in traces
        for call in (trace.get("tools") or [])
    ]
    event_counts = Counter(str(event.get("type") or "") for event in events)
    node_counts = Counter(str(trace.get("node_id") or "") for trace in traces)
    routing = []
    for trace in traces:
        if trace.get("node_id") != "route":
            continue
        output = trace.get("output") if isinstance(trace.get("output"), dict) else {}
        value = output.get("structured") or output.get("value")
        if isinstance(value, dict) and value.get("profile"):
            routing.append({"profile": value.get("profile"), "reason": value.get("reason")})
    context_events = [
        {"type": event.get("type"), "data": event.get("data")}
        for event in events
        if event.get("type") in {
            "conversation_applied", "tool_results_pruned", "context_compacted",
            "context_compaction_started", "context_compaction_failed",
        }
    ]
    native = native_trajectory_evidence(str(run.get("id")))
    return {
        "run_id": run.get("id"),
        "task_id": run.get("task_id"),
        "status": run.get("status"),
        "score": (run.get("evaluation") or {}).get("score"),
        "flow": (run.get("selection") or {}).get("harness"),
        "flow_version": (run.get("selection") or {}).get("harness_version"),
        "stats": run.get("stats") or {},
        "steps": [
            {"id": step.get("id"), "status": step.get("status"), "score": (step.get("evaluation") or {}).get("score")}
            for step in (run.get("task_steps") or [])
        ],
        "tool_calls": dict(tool_names=tool_names, counts=Counter(tool_names)),
        "node_counts": dict(node_counts),
        "routing": routing,
        "event_counts": dict(event_counts),
        "context_events": context_events,
        "delegation": {
            "create_harness_tool_calls": tool_names.count("create_harness"),
            "component_subflows": native["component_subflows"],
            "autonomous_subagents": native["autonomous_subagents"],
        },
        "native_trajectory": native,
        "evolution_events": run.get("evolution_events") or [],
        "mutations": run.get("mutations") or {},
        "error": run.get("error"),
        "run_file": str((ROOT / ".egoagent" / "task_runs" / str(run.get("id")) / "run.json").resolve()),
    }


def wait_for_run(manager: TaskBenchManager, run_id: str, poll_seconds: float = 5.0) -> dict:
    last_signature = None
    while True:
        state = manager.get(run_id)
        signature = (state.get("status"), state.get("task_step"), state.get("current_node"), state.get("step_count"))
        if signature != last_signature:
            print(
                f"[{run_id}] status={signature[0]} task_step={signature[1]} "
                f"node={signature[2]} graph_steps={signature[3]}",
                flush=True,
            )
            last_signature = signature
        if not state.get("running"):
            return state
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_TASKS)
    parser.add_argument("--flows", nargs="+", default=DEFAULT_FLOWS)
    parser.add_argument("--identity", default="adaptive_deepseek_coder")
    parser.add_argument(
        "--primary-slot-identity",
        default="",
        help="Bind the primary agent and governor slots to an isolated Identity while retaining reviewer defaults.",
    )
    parser.add_argument(
        "--governor-identity",
        default="",
        help="Optionally bind only the governor slot; useful for lightweight context-policy parity runs.",
    )
    parser.add_argument("--label", default="manual")
    args = parser.parse_args()

    loaded = load_local_env(ROOT)
    print("Loaded provider variable names:", ", ".join(loaded) if loaded else "already present", flush=True)
    manager = TaskBenchManager(ROOT)
    output_dir = ROOT / "experiments" / "product_code_agent_acceptance" / "results" / (
        time.strftime("%Y%m%d_%H%M%S") + "_" + args.label
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "ego.product-code-acceptance.v1",
        "created_at": time.time(),
        "tasks": args.tasks,
        "flows": args.flows,
        "identity": args.identity,
        "primary_slot_identity": args.primary_slot_identity,
        "governor_identity": args.governor_identity,
        "runs": [],
    }

    for task_id in args.tasks:
        for flow in args.flows:
            print(f"START task={task_id} flow={flow}", flush=True)
            try:
                created = manager.start({
                    "task_id": task_id,
                    "harness": flow,
                    "identity": args.identity,
                    "slot_bindings": {
                        **({"agent": args.primary_slot_identity} if args.primary_slot_identity else {}),
                        **(
                            {"governor": args.governor_identity}
                            if args.governor_identity
                            else ({"governor": args.primary_slot_identity} if args.primary_slot_identity else {})
                        ),
                    },
                    "debug_mode": "auto",
                })
                state = wait_for_run(manager, created["id"])
                summary = analyze(state)
            except (TaskBenchError, OSError, ValueError) as error:
                # One invalid matrix cell must remain auditable without losing
                # every later treatment.  Runtime failures inside a started
                # task are already represented by ``analyze(state)``.
                summary = {
                    "run_id": None,
                    "task_id": task_id,
                    "status": "error",
                    "score": None,
                    "flow": flow,
                    "flow_version": None,
                    "stats": {},
                    "steps": [],
                    "tool_calls": {"tool_names": [], "counts": {}},
                    "node_counts": {},
                    "routing": [],
                    "event_counts": {},
                    "context_events": [],
                    "delegation": {},
                    "native_trajectory": {},
                    "evolution_events": [],
                    "mutations": {},
                    "error": f"{type(error).__name__}: {error}",
                    "run_file": None,
                }
            report["runs"].append(summary)
            (output_dir / f"{task_id}__{flow}.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"DONE task={task_id} flow={flow} status={summary['status']} "
                f"score={summary['score']} error={summary['error'] or '-'}",
                flush=True,
            )

    print(f"REPORT {output_dir / 'report.json'}", flush=True)
    return 0 if all(item["status"] == "passed" for item in report["runs"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
