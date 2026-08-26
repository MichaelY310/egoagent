"""Issue an EvoCert from a completed Harness-Bench Fast layer pilot.

This adapter is deliberately conservative: a single-artifact certificate can
use the real paired validation/held-out task results, but the decision remains
``abstain`` until the pilot also records protected-task, portability and
semantic-verifier-mutation evidence.  Missing research evidence is never
silently replaced by synthetic scores.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from self_evolution.evolution_certificate import issue_evolution_certificate  # noqa: E402


def _cell_success(cell: dict[str, Any]) -> float:
    return 1.0 if cell.get("success") is True else 0.0


def build_payload(report: dict[str, Any], family_name: str) -> dict[str, Any]:
    family = next((item for item in report.get("families", []) if item.get("family") == family_name), None)
    if family is None:
        raise ValueError(f"family not found: {family_name}")
    layer = str((family.get("selection") or {}).get("kind", "none"))
    if layer == "none":
        raise ValueError("the empirical selector promoted no artifact")
    rows = family.get("rows") or []
    measurements = []
    for row in rows:
        split = str(row.get("split", ""))
        if split not in {"validation", "heldout"}:
            continue
        task_id = f"{row.get('task_id')}:r{row.get('repetition', 1)}"
        measurements.extend([
            {"split": split, "task_id": task_id, "active_artifacts": [], "success": _cell_success(row.get("static") or {}), "within_budget": True},
            {"split": split, "task_id": task_id, "active_artifacts": [layer], "success": _cell_success(row.get(layer) or {}), "within_budget": (row.get(layer) or {}).get("status") not in {"timeout", "error", "stopped"}},
        ])

    # The generic certificate requires a protected split.  With no protected
    # benchmark executions, provide explicit missing measurements by raising a
    # structured preflight result rather than fabricating neutral performance.
    return {
        "ready": False,
        "update_id": f"harnessbench-{family_name}-{layer}",
        "selected_artifact": layer,
        "real_measurements": measurements,
        "missing_evidence": [
            "paired protected-task executions",
            "fresh identity/model graft executions",
            "semantic verifier mutants with kill outcomes",
            "at least two repetitions per split for uncertainty estimation",
        ],
        "reason": "Real validation/held-out evidence exists, but issuing a publishable certificate would require fabricated evidence; refusing to do so.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--family", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = build_payload(report, args.family)
    output = args.output or args.report.with_name(f"evocert_preflight_{args.family}.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 2 if not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
