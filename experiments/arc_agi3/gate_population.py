"""Promote one population candidate from paired validation/held-out evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flow_variants import FlowVariantError, paired_flow_promotion_decision


def metrics(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    outcome = payload.get("official_outcome") or {}
    stats = payload.get("stats") or {}
    return {
        "levels_completed": outcome.get("total_levels_completed", 0) or 0,
        "score": outcome.get("score", 0) or 0,
        "actions": outcome.get("total_actions", 0) or 0,
        "model_calls": stats.get("model_calls", 0) or 0,
        "tokens": (stats.get("input_tokens_actual", 0) or 0) + (stats.get("output_tokens_actual", 0) or 0),
        "elapsed_seconds": payload.get("elapsed_seconds", 0) or 0,
        "run_id": payload.get("run_id"),
    }


def build_pairs(matrix: dict, candidate_id: str, matrix_path: Path) -> tuple[list[dict], list[dict]]:
    validation: list[dict] = []
    heldout: list[dict] = []
    for item in matrix.get("cases", []):
        if not isinstance(item, dict):
            continue
        candidates = item.get("candidate_results") or {}
        if candidate_id not in candidates:
            continue
        baseline_path = Path(str(item.get("baseline_result", "")))
        candidate_path = Path(str(candidates[candidate_id]))
        if not baseline_path.is_absolute():
            baseline_path = (matrix_path.parent / baseline_path).resolve()
        if not candidate_path.is_absolute():
            candidate_path = (matrix_path.parent / candidate_path).resolve()
        pair = {
            "case_id": str(item.get("case_id", "")),
            "baseline": metrics(baseline_path),
            "candidate": metrics(candidate_path),
        }
        split = str(item.get("split", "validation")).lower()
        (heldout if split == "heldout" else validation).append(pair)
    return validation, heldout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--min-validation", type=int, default=2)
    parser.add_argument("--min-heldout", type=int, default=2)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    try:
        validation, heldout = build_pairs(matrix, args.candidate_id, args.matrix)
        decision = paired_flow_promotion_decision(
            validation,
            heldout,
            primary_metrics=["levels_completed", "score"],
            # Wall time is retained for diagnostics but is too noisy to
            # promote a Flow.  Require reproducible algorithmic savings.
            cost_metrics=["actions", "tokens", "model_calls"],
            min_validation_cases=max(1, args.min_validation),
            min_heldout_cases=max(1, args.min_heldout),
            max_primary_losses=0,
            min_cost_improvement=0.05,
        )
    except (FlowVariantError, OSError, ValueError, json.JSONDecodeError) as error:
        decision = {"status": "invalid_evidence", "promoted": False, "reason": str(error)}
    for candidate in report.get("candidates", []):
        if candidate.get("candidate_id") == args.candidate_id:
            candidate["evaluation_status"] = decision["status"]
            candidate["evaluation"] = decision
    report.setdefault("promotion_attempts", []).append({
        "candidate_id": args.candidate_id,
        "matrix": str(args.matrix.resolve()),
        "decision": decision,
    })
    report["promoted"] = bool(decision.get("promoted"))
    report["promoted_candidate_id"] = args.candidate_id if decision.get("promoted") else None
    report["promotion_reason"] = decision.get("reason")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision.get("promoted") else 3


if __name__ == "__main__":
    raise SystemExit(main())
