"""Legacy single-pair diagnostic gate (cannot promote a Flow)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flow_variants import flow_promotion_decision


def _metrics(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    outcome = payload.get("official_outcome") or {}
    stats = payload.get("stats") or {}
    return {
        "levels_completed": outcome.get("total_levels_completed", 0),
        "score": outcome.get("score", 0),
        "actions": outcome.get("total_actions", 0),
        "tokens": (stats.get("input_tokens_actual", 0) or 0) + (stats.get("output_tokens_actual", 0) or 0),
        "elapsed_seconds": payload.get("elapsed_seconds", 0),
        "run_id": payload.get("run_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--heldout-verified", action="store_true", help="Deprecated; use gate_population.py with result files")
    args = parser.parse_args()
    if args.heldout_verified:
        parser.error(
            "a boolean is no longer accepted as held-out evidence; use gate_population.py "
            "with an evaluation_matrix.json containing paired result files"
        )
    report = json.loads(args.report.read_text(encoding="utf-8"))
    baseline = _metrics(args.baseline)
    candidate = _metrics(args.candidate)
    decision = flow_promotion_decision(
        baseline,
        candidate,
        primary_metrics=["levels_completed", "score"],
        cost_metrics=["actions", "tokens", "elapsed_seconds"],
        heldout_verified=False,
    )
    report["evaluation"] = {"baseline": baseline, "candidate": candidate, "decision": decision}
    report["promoted"] = decision["promoted"]
    report["promotion_reason"] = decision["reason"]
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["evaluation"], ensure_ascii=False, indent=2))
    return 0 if decision["promoted"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
