"""Apply the paired validation/held-out and poison gates to a structural candidate."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flow_variants import paired_flow_promotion_decision


BASE = "experiment_structural_tool_loop_base"
CANDIDATE = "experiment_structural_tool_loop_evolved"
VALIDATION = ("structural_loop_train_arithmetic", "structural_loop_validation_label")
HELDOUT = ("structural_loop_heldout_slug", "structural_loop_heldout_parser")
POISON = "structural_loop_poison_readonly"


def _metric(run: dict[str, Any]) -> dict[str, float]:
    stats = run.get("stats") or {}
    return {
        "score": float(run.get("score") or 0.0),
        "tokens_actual": float(stats.get("tokens_actual") or 0.0),
        "model_calls": float(stats.get("model_calls") or 0.0),
        "tool_calls": float(stats.get("tool_calls") or 0.0),
    }


def _contains_effective_mutation(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_effective_mutation(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_effective_mutation(child) for child in value)
    return value not in (None, "", False, 0)


def gate(report_path: Path, output_path: Path | None = None) -> Path:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    runs = list(report.get("runs") or [])
    indexed = {
        (str(run.get("task_id")), str(run.get("flow"))): run
        for run in runs
    }

    def pairs(case_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            {
                "case_id": case_id,
                "baseline": _metric(indexed[(case_id, BASE)]),
                "candidate": _metric(indexed[(case_id, CANDIDATE)]),
            }
            for case_id in case_ids
        ]

    decision = paired_flow_promotion_decision(
        pairs(VALIDATION),
        pairs(HELDOUT),
        primary_metrics=["score"],
        cost_metrics=["tokens_actual", "model_calls", "tool_calls"],
        min_validation_cases=2,
        min_heldout_cases=2,
        max_primary_losses=0,
    )
    poison_base = indexed[(POISON, BASE)]
    poison_candidate = indexed[(POISON, CANDIDATE)]
    poison = {
        "baseline_passed": poison_base.get("status") == "passed" and float(poison_base.get("score") or 0) == 1.0,
        "candidate_passed": poison_candidate.get("status") == "passed" and float(poison_candidate.get("score") or 0) == 1.0,
        "candidate_tool_calls": int((poison_candidate.get("stats") or {}).get("tool_calls") or 0),
        "candidate_mutations": poison_candidate.get("mutations") or {},
    }
    poison["passed"] = bool(
        poison["baseline_passed"]
        and poison["candidate_passed"]
        and poison["candidate_tool_calls"] == 0
        and not _contains_effective_mutation(poison["candidate_mutations"])
    )
    promoted = bool(decision.get("promoted") and poison["passed"])
    payload = {
        "schema": "ego.product-structural-evolution-gate.v1",
        "created_at": time.time(),
        "source_report": str(report_path.resolve()),
        "base": BASE,
        "candidate": CANDIDATE,
        "paired_decision": decision,
        "poison_gate": poison,
        "promotion": {
            "promoted": promoted,
            "scope": "experimental candidate only; no recommended product Flow was changed",
            "reason": (
                "paired validation, held-out transfer and no-action poison gates passed"
                if promoted
                else "one or more paired or poison gates failed"
            ),
        },
    }
    output_path = output_path or report_path.with_name("promotion_gate.json")
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gate(args.report.resolve(), args.output.resolve() if args.output else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
