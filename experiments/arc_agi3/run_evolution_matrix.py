"""Run a baseline and Flow-variant population on paired ARC cases."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.env_config import load_local_env
from experiments.arc_agi3.run_deepseek_pilot import run_flow


def parse_cases(values: list[str], split: str) -> list[dict]:
    cases = []
    for value in values:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError(f"case must be GAME:SEED, got {value!r}")
        game, seed = parts
        cases.append({"case_id": f"{split}:{game}:{int(seed)}", "split": split, "game": game, "seed": int(seed)})
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--validation", action="append", default=[] , metavar="GAME:SEED")
    parser.add_argument("--heldout", action="append", default=[], metavar="GAME:SEED")
    parser.add_argument("--actions", type=int, default=8)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--candidate-limit", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    load_local_env(ROOT)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    cases = parse_cases(args.validation, "validation") + parse_cases(args.heldout, "heldout")
    if not cases:
        raise SystemExit("at least one --validation or --heldout GAME:SEED is required")
    candidates = list(report.get("candidates", []))
    if args.candidate_limit > 0:
        candidates = candidates[:args.candidate_limit]
    if not candidates:
        raise SystemExit("evolution report has no valid candidates")
    output = args.output or args.report.parent / "evaluation_matrix.json"
    matrix = {
        "format": "ego.flow-evolution-matrix.v1",
        "created_at": time.time(),
        "report": str(args.report.resolve()),
        "base_flow": report.get("base_flow", "arc_scientific_search"),
        "action_budget": max(1, args.actions),
        "cases": [],
    }
    for case in cases:
        baseline = run_flow(
            matrix["base_flow"], case["game"], max(1, args.actions), case["seed"],
            token_budget=args.token_budget,
        )
        record = {
            **case,
            "baseline_result": baseline["result_path"],
            "candidate_results": {},
        }
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            candidate_result = run_flow(
                candidate_id,
                case["game"],
                max(1, args.actions),
                case["seed"],
                token_budget=args.token_budget,
                config_path=candidate["path"],
            )
            record["candidate_results"][candidate_id] = candidate_result["result_path"]
        matrix["cases"].append(record)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(matrix, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
