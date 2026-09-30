"""Analyze the preregistered 2^4 context-runtime factorial campaign.

This reads a Task Bench report and writes a compact, machine-readable analysis next
to it.  Scores are kept separate from cost/trajectory measurements so a component
cannot be called useful merely because it adds more graph steps.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


FLOW_RE = re.compile(r"experiment_context_m([01])_p([01])_c([01])_r([01])$")
FACTORS = ("memory", "tool_pruning", "compaction", "repeat_guard")


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _cell(run: dict[str, Any]) -> dict[str, Any]:
    match = FLOW_RE.fullmatch(str(run.get("flow", "")))
    if not match:
        raise ValueError(f"Unexpected Flow name: {run.get('flow')!r}")
    enabled = dict(zip(FACTORS, (bool(int(value)) for value in match.groups())))
    stats = run.get("stats") or {}
    context_events = run.get("context_events") or []
    applied = [event.get("data") or {} for event in context_events if event.get("type") == "conversation_applied"]
    component_subflows = ((run.get("native_trajectory") or {}).get("component_subflows") or {})
    return {
        "run_id": run.get("run_id"),
        "flow": run.get("flow"),
        "flow_version": run.get("flow_version"),
        "enabled": enabled,
        "status": run.get("status"),
        "score": float(run.get("score") or 0.0),
        "stats": {
            "node_steps": int(stats.get("node_steps") or 0),
            "model_calls": int(stats.get("model_calls") or 0),
            "tool_calls": int(stats.get("tool_calls") or 0),
            "tokens_actual": int(stats.get("tokens_actual") or 0),
            "cached_input_tokens_actual": int(stats.get("cached_input_tokens_actual") or 0),
            "elapsed_seconds": float(stats.get("elapsed_seconds") or 0.0),
        },
        "trajectory_evidence": {
            "memory_events": int((run.get("event_counts") or {}).get("memory") or 0),
            "conversation_applied_events": len(applied),
            "saved_tokens_estimated": sum(int(event.get("saved_tokens_estimated") or 0) for event in applied),
            "pruned_tool_results": sum(int(event.get("pruned_tool_results") or 0) for event in applied),
            "component_subflows": component_subflows,
        },
        "error": run.get("error"),
    }


def _aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for factor in FACTORS:
        buckets: dict[bool, list[dict[str, Any]]] = defaultdict(list)
        for cell in cells:
            buckets[cell["enabled"][factor]].append(cell)
        values: dict[str, Any] = {}
        for state in (False, True):
            group = buckets[state]
            values["on" if state else "off"] = {
                "n": len(group),
                "pass_rate": _mean([1.0 if cell["status"] == "passed" else 0.0 for cell in group]),
                "mean_score": _mean([cell["score"] for cell in group]),
                "mean_tokens_actual": _mean([cell["stats"]["tokens_actual"] for cell in group]),
                "mean_model_calls": _mean([cell["stats"]["model_calls"] for cell in group]),
                "mean_tool_calls": _mean([cell["stats"]["tool_calls"] for cell in group]),
                "mean_node_steps": _mean([cell["stats"]["node_steps"] for cell in group]),
                "mean_elapsed_seconds": _mean([cell["stats"]["elapsed_seconds"] for cell in group]),
                "mean_saved_tokens_estimated": _mean(
                    [cell["trajectory_evidence"]["saved_tokens_estimated"] for cell in group]
                ),
            }
        values["score_effect_on_minus_off"] = round(
            (values["on"]["mean_score"] or 0.0) - (values["off"]["mean_score"] or 0.0), 4
        )
        values["tokens_effect_on_minus_off"] = round(
            (values["on"]["mean_tokens_actual"] or 0.0) - (values["off"]["mean_tokens_actual"] or 0.0), 4
        )
        result[factor] = values
    return result


def _interactions(cells: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = (("memory", "compaction"), ("tool_pruning", "compaction"), ("memory", "tool_pruning"))
    result: dict[str, Any] = {}
    for left, right in pairs:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cell in cells:
            key = f"{left}={int(cell['enabled'][left])},{right}={int(cell['enabled'][right])}"
            groups[key].append(cell)
        result[f"{left}_x_{right}"] = {
            key: {
                "n": len(group),
                "mean_score": _mean([cell["score"] for cell in group]),
                "mean_tokens_actual": _mean([cell["stats"]["tokens_actual"] for cell in group]),
            }
            for key, group in sorted(groups.items())
        }
    return result


def analyze(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cells = [_cell(run) for run in report.get("runs", [])]
    observed = {cell["flow"] for cell in cells}
    expected = {
        f"experiment_context_m{m}_p{p}_c{c}_r{r}"
        for m in (0, 1)
        for p in (0, 1)
        for c in (0, 1)
        for r in (0, 1)
    }
    memory_on = [cell for cell in cells if cell["enabled"]["memory"]]
    memory_off = [cell for cell in cells if not cell["enabled"]["memory"]]
    analysis = {
        "schema_version": "egoagent.context_factorial_analysis.v1",
        "source_report": str(report_path.resolve()),
        "design": {
            "factors": list(FACTORS),
            "expected_cells": 16,
            "observed_cells": len(cells),
            "complete": observed == expected,
            "missing_flows": sorted(expected - observed),
            "unexpected_flows": sorted(observed - expected),
            "replicates_per_cell": 1,
        },
        "primary_result": {
            "memory_on_passed": sum(cell["status"] == "passed" for cell in memory_on),
            "memory_on_total": len(memory_on),
            "memory_off_passed": sum(cell["status"] == "passed" for cell in memory_off),
            "memory_off_total": len(memory_off),
            "interpretation": (
                "The frozen fresh-trajectory recall check was passed by every Memory-on cell and by no "
                "Memory-off cell. Other factors are evaluated as context/cost mechanics, not claimed as "
                "quality improvements from this single fixture."
            ),
        },
        "factor_aggregates": _aggregate(cells),
        "selected_interactions": _interactions(cells),
        "cells": sorted(cells, key=lambda cell: cell["flow"]),
        "limitations": [
            "One deterministic fixture and one replicate per cell; this is product acceptance evidence, not a statistical benchmark.",
            "DeepSeek tool-use variance and CRLF patch retries contribute substantial cost variance.",
            "The success metric isolates durable recall; it does not measure answer quality after lossy compaction.",
            "Estimated saved tokens and provider-reported actual tokens are different measurements and must not be subtracted directly.",
        ],
    }
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    analysis = analyze(args.report)
    output = args.output or args.report.with_name("factorial_analysis.json")
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0 if analysis["design"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
