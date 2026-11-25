"""Transparent post-hoc validity audit for an EvoCert pilot report.

This module does not replace or modify the preregistered ``analysis.json``.
It audits two limitations discovered while inspecting real trajectories:

* the frozen Knowledge activation flag means the artifact was advertised in
  the model tool schema, not necessarily invoked or consumed; and
* a protected task whose incumbent success is zero cannot demonstrate
  non-regression, because the comparison is already at the metric floor.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from experiments.evocert_real_pilot.analyze import VARIANTS


KNOWLEDGE_VARIANTS = ("K", "IK", "KF", "IKF")


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _cells(family: dict[str, Any], *, split: str | None = None, variants=VARIANTS):
    for row in family.get("rows") or []:
        if split is not None and row.get("split") != split:
            continue
        for variant in variants:
            cell = row.get(variant)
            if isinstance(cell, dict):
                yield row, variant, cell


def _invoked(cell: dict[str, Any], capability_name: str) -> bool:
    return any(
        str(tool.get("name") or "") == capability_name
        for tool in cell.get("tools") or []
        if isinstance(tool, dict)
    )


def audit_family(family: dict[str, Any]) -> dict[str, Any]:
    family_name = str(family.get("family") or "")
    capability_name = f"{family_name}_operation_protocol"
    knowledge_cells = [
        cell for _row, _variant, cell in _cells(family, variants=KNOWLEDGE_VARIANTS)
    ]
    advertised = [
        1.0 if (cell.get("activation") or {}).get("K") else 0.0
        for cell in knowledge_cells
    ]
    invoked = [1.0 if _invoked(cell, capability_name) else 0.0 for cell in knowledge_cells]

    protected_rows = [row for row in family.get("rows") or [] if row.get("split") == "protected"]
    protected_tasks = []
    for row in protected_rows:
        incumbent = row.get("none") if isinstance(row.get("none"), dict) else {}
        baseline = float(incumbent.get("success", 0.0))
        protected_tasks.append({
            "task_id": row.get("task_id"),
            "incumbent_success": baseline,
            "at_metric_floor": baseline <= 0.0,
            "can_detect_success_regression": baseline > 0.0,
        })

    runtime_cells = [cell for _row, _variant, cell in _cells(family)]
    return {
        "family": family_name,
        "knowledge_activation": {
            "capability_name": capability_name,
            "n_cells": len(knowledge_cells),
            "advertised_rate": _mean(advertised),
            "invoked_rate": _mean(invoked),
            "consumed_rate": None,
            "consumed_rate_note": (
                "The condensed report cannot prove that a capability result influenced a later model call; "
                "use raw node traces for consumption analysis."
            ),
        },
        "protected_gate": {
            "tasks": protected_tasks,
            "all_incumbents_at_floor": bool(protected_tasks) and all(
                item["at_metric_floor"] for item in protected_tasks
            ),
            "non_regression_claim_informative": bool(protected_tasks) and all(
                item["can_detect_success_regression"] for item in protected_tasks
            ),
        },
        "runtime": {
            "n_cells": len(runtime_cells),
            "error_count": sum(
                1 for cell in runtime_cells
                if cell.get("runtime_error") or cell.get("status") in {"error", "timeout", "stopped"}
            ),
        },
    }


def audit_report(report: dict[str, Any]) -> dict[str, Any]:
    families = [audit_family(family) for family in report.get("families") or []]
    return {
        "format": "ego.evocert-real-pilot-posthoc-audit.v1",
        "source_run": report.get("stamp"),
        "status": "post-hoc; does not replace the preregistered analysis",
        "families": families,
        "summary": {
            "knowledge_advertised_but_never_invoked_families": [
                item["family"] for item in families
                if item["knowledge_activation"]["advertised_rate"] > 0
                and item["knowledge_activation"]["invoked_rate"] == 0
            ],
            "protected_floor_effect_families": [
                item["family"] for item in families
                if item["protected_gate"]["all_incumbents_at_floor"]
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = audit_report(report)
    destination = args.output or args.report.with_name("posthoc_audit.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
