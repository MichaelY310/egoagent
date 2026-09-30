"""Normalize and summarize P6 EgoAgent-vs-upstream-Codex product runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_run_state(run: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(run.get("run_file") or ""))
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _elapsed(run: dict[str, Any], state: dict[str, Any]) -> float:
    stats = run.get("stats") or {}
    if stats.get("elapsed_seconds") is not None:
        return float(stats["elapsed_seconds"])
    started = state.get("started_at")
    completed = state.get("completed_at")
    if started is None or completed is None:
        return 0.0
    return max(0.0, float(completed) - float(started))


def _trajectory_evidence(run: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    runner = run.get("runner")
    run_file = Path(str(run.get("run_file") or ""))
    if runner == "codex_cli":
        raw_files = sorted(run_file.parent.glob("codex-*.jsonl")) if run_file.is_file() else []
        lines = []
        parse_errors = 0
        for path in raw_files:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                lines.append(line)
                try:
                    json.loads(line)
                except ValueError:
                    parse_errors += 1
        return {
            "kind": "upstream_codex_jsonl",
            "raw_files": [str(path.resolve()) for path in raw_files],
            "raw_events": len(lines),
            "json_parse_errors": parse_errors,
            "projected_events": len(state.get("events") or []),
            "complete": bool(raw_files) and bool(lines) and parse_errors == 0,
        }
    native = run.get("native_trajectory") or {}
    files = [Path(str(value)) for value in native.get("files") or []]
    return {
        "kind": "egoagent_lossless_trajectory",
        "files": [str(path.resolve()) for path in files if path.is_file()],
        "event_counts": native.get("event_counts") or {},
        "component_subflows": native.get("component_subflows") or {},
        "autonomous_subagents": native.get("autonomous_subagents") or {},
        "complete": bool(files) and all(path.is_file() for path in files),
    }


def analyze(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cells = []
    for run in report.get("runs", []):
        state = _load_run_state(run)
        stats = run.get("stats") or {}
        is_codex = run.get("runner") == "codex_cli"
        provider_tokens = int((stats.get("total_tokens") if is_codex else stats.get("tokens_actual")) or 0)
        cached_tokens = int(
            (stats.get("cached_input_tokens") if is_codex else stats.get("cached_input_tokens_actual")) or 0
        )
        native = run.get("native_trajectory") or {}
        autonomous = native.get("autonomous_subagents") or {}
        cells.append({
            "task_id": run.get("task_id"),
            "lane": run.get("lane"),
            "runner": run.get("runner"),
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "score": float(run.get("score") or 0.0),
            "flow": run.get("flow"),
            "version": (
                ((run.get("runner_metadata") or {}).get("version")) if is_codex else run.get("flow_version")
            ),
            "metrics": {
                "elapsed_seconds": round(_elapsed(run, state), 3),
                "provider_reported_tokens": provider_tokens,
                "cached_input_tokens": cached_tokens,
                "model_calls": int(stats.get("model_calls") or 0),
                "tool_calls": int(stats.get("tool_calls") or 0),
                "node_steps": None if is_codex else int(stats.get("node_steps") or 0),
                "autonomous_child_runs": sum(int(value or 0) for value in autonomous.values()),
            },
            "trajectory": _trajectory_evidence(run, state),
            "error": run.get("error"),
        })

    task_summaries = []
    for task_id in sorted({cell["task_id"] for cell in cells}):
        group = [cell for cell in cells if cell["task_id"] == task_id]
        passed = [cell for cell in group if cell["status"] == "passed"]
        task_summaries.append({
            "task_id": task_id,
            "passed_lanes": len(passed),
            "total_lanes": len(group),
            "lowest_reported_tokens_lane": min(
                passed, key=lambda cell: cell["metrics"]["provider_reported_tokens"]
            )["lane"] if passed else None,
            "fastest_wall_time_lane": min(
                passed, key=lambda cell: cell["metrics"]["elapsed_seconds"]
            )["lane"] if passed else None,
        })
    expected = len(report.get("tasks") or []) * len(report.get("lanes") or [])
    return {
        "schema_version": "egoagent.product_comparison_analysis.v1",
        "source_report": str(report_path.resolve()),
        "complete": len(cells) == expected and all(cell["status"] == "passed" for cell in cells),
        "expected_cells": expected,
        "observed_cells": len(cells),
        "trajectory_complete_cells": sum(bool(cell["trajectory"]["complete"]) for cell in cells),
        "task_summaries": task_summaries,
        "cells": cells,
        "caveats": [
            "This is a cross-provider product comparison, not a same-model causal ablation.",
            "Provider-reported token accounting is not assumed semantically identical across DeepSeek and Codex.",
            "EgoAgent node steps and projected upstream Codex events are different units and are not ranked together.",
            "One replicate per cell is a smoke comparison, not a statistically powered leaderboard.",
        ],
    }


def _markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# P6 product comparison result", "",
        "> Cross-provider product smoke comparison; do not interpret as a same-model ablation.", "",
        "| Task | Lane | Score | Seconds | Provider tokens | Cached | Model | Tools | Child | Trajectory |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for cell in analysis["cells"]:
        metrics = cell["metrics"]
        lines.append(
            f"| `{cell['task_id']}` | `{cell['lane']}` | {cell['score']:.2f} | "
            f"{metrics['elapsed_seconds']:.1f} | {metrics['provider_reported_tokens']:,} | "
            f"{metrics['cached_input_tokens']:,} | {metrics['model_calls']} | {metrics['tool_calls']} | "
            f"{metrics['autonomous_child_runs']} | {'complete' if cell['trajectory']['complete'] else 'incomplete'} |"
        )
    lines.extend(["", "## Honest interpretation", ""])
    for caveat in analysis["caveats"]:
        lines.append(f"- {caveat}")
    lines.extend(["", f"All cells passed: **{analysis['complete']}**.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    analysis = analyze(args.report)
    json_path = args.report.with_name("product_comparison_analysis.json")
    md_path = args.report.with_name("PRODUCT_COMPARISON_RESULT.md")
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(analysis), encoding="utf-8")
    print(json_path.resolve())
    print(md_path.resolve())
    return 0 if analysis["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
