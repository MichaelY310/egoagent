"""Analyze the preregistered P5 single-vs-Team size ladder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SIZES = ("small", "medium", "large")
ARMS = ("code_agent_long", "code_agent_team")
ROOT = Path(__file__).resolve().parents[2]


def _sum_autonomous(run: dict[str, Any]) -> int:
    native = run.get("native_trajectory") or {}
    children = native.get("autonomous_subagents") or {}
    return sum(int(value or 0) for value in children.values())


def analyze(report_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_cell = {(run.get("task_id"), run.get("flow")): run for run in report.get("runs", [])}
    cells = []
    missing = []
    for size in SIZES:
        task_id = f"team_threshold_{size}"
        # Reports normally live under experiments/.../results/<run>/; locate repo
        # robustly instead of relying on a fixed result depth.
        task = json.loads((root / "task_bench" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
        fixture = ((task.get("experiment") or {}).get("team_threshold") or {})
        for arm in ARMS:
            run = by_cell.get((task_id, arm))
            if not run:
                missing.append(f"{task_id}:{arm}")
                continue
            stats = run.get("stats") or {}
            autonomous = _sum_autonomous(run)
            cells.append({
                "size": size,
                "task_id": task_id,
                "arm": arm,
                "run_id": run.get("run_id"),
                "flow_version": run.get("flow_version"),
                "status": run.get("status"),
                "score": run.get("score"),
                "workspace_files": fixture.get("workspace_files"),
                "workspace_bytes": fixture.get("workspace_bytes"),
                "autonomous_child_runs": autonomous,
                "autonomous_subagents": ((run.get("native_trajectory") or {}).get("autonomous_subagents") or {}),
                "stats": {
                    "tokens_actual": int(stats.get("tokens_actual") or 0),
                    "model_calls": int(stats.get("model_calls") or 0),
                    "tool_calls": int(stats.get("tool_calls") or 0),
                    "node_steps": int(stats.get("node_steps") or 0),
                    "elapsed_seconds": float(stats.get("elapsed_seconds") or 0.0),
                },
                "error": run.get("error"),
            })
    pairs = []
    for size in SIZES:
        pair = {cell["arm"]: cell for cell in cells if cell["size"] == size}
        if len(pair) != 2:
            continue
        single, team = pair["code_agent_long"], pair["code_agent_team"]
        pairs.append({
            "size": size,
            "single_score": single["score"],
            "team_score": team["score"],
            "team_children": team["autonomous_child_runs"],
            "score_delta_team_minus_single": round(float(team["score"] or 0) - float(single["score"] or 0), 4),
            "token_delta_team_minus_single": team["stats"]["tokens_actual"] - single["stats"]["tokens_actual"],
            "elapsed_delta_team_minus_single": round(
                team["stats"]["elapsed_seconds"] - single["stats"]["elapsed_seconds"], 4
            ),
        })
    return {
        "schema_version": "egoagent.team_threshold_analysis.v1",
        "source_report": str(report_path.resolve()),
        "complete": not missing and len(cells) == 6,
        "missing_cells": missing,
        "cells": cells,
        "paired_effects": pairs,
        "interpretation_rules": [
            "A child launch is evidence of delegation, not evidence of benefit.",
            "Below-gate cells should launch zero autonomous children.",
            "If both arms pass and Team costs more, Team remains opt-in at that size.",
            "One replicate per cell is product acceptance evidence, not a statistical quality claim.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    analysis = analyze(args.report)
    output = args.report.with_name("team_threshold_analysis.json")
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0 if analysis["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
