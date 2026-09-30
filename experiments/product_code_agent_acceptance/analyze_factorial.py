"""Analyze pre-registered 2x2 EgoAgent feature ablations.

The input is one or more ``run_matrix.py`` reports.  The script treats provider
usage as authoritative, checks that every cell is correct, and reports the
standard difference-of-differences interaction for lower-is-better metrics.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


STUDIES = {
    "pruning_compaction": {
        "title": "Tool-result pruning × passive compaction",
        "factors": ["tool pruning", "passive compaction"],
        "cells": {
            "00": "product_adaptive_tool_pruning_off",
            "10": "product_adaptive_tool_pruning_on",
            "01": "product_adaptive_compaction_only",
            "11": "product_adaptive_context_combo",
        },
        "expected_modes": {"10": ["tool_prune"], "01": ["block_plan"], "11": ["tool_prune", "block_plan"]},
    },
    "curation_compaction": {
        "title": "Model-authored curation × passive compaction",
        "factors": ["periodic curation", "passive compaction"],
        "cells": {
            "00": "product_context_endurance_ungoverned",
            "10": "product_context_endurance_curation_only",
            "01": "product_context_endurance_compaction_only",
            "11": "product_context_endurance_governed",
        },
        "expected_modes": {"10": ["turn_plan"], "01": ["block_plan"], "11": ["turn_plan", "block_plan"]},
    },
}


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def modes(run: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    native = (run.get("native_trajectory") or {}).get("context_changes") or []
    fallback = run.get("context_events") or []
    for item in [*native, *fallback]:
        mode = item.get("mode")
        if mode is None and isinstance(item.get("data"), dict):
            mode = item["data"].get("mode")
        if mode:
            counts[str(mode)] = counts.get(str(mode), 0) + 1
    return counts


def summarize_cell(runs: list[dict], expected_modes: list[str]) -> dict:
    usage = [run.get("stats") or {} for run in runs]
    mode_counts: dict[str, int] = {}
    for run in runs:
        for name, count in modes(run).items():
            mode_counts[name] = mode_counts.get(name, 0) + count
    successful = [run for run in runs if run.get("status") == "passed" and run.get("score") == 1.0]
    tokens = [float(item["tokens_actual"]) for item in usage if item.get("tokens_actual") is not None]
    elapsed = [float(item["elapsed_seconds"]) for item in usage if item.get("elapsed_seconds") is not None]
    calls = [float(item["model_calls"]) for item in usage if item.get("model_calls") is not None]
    uncached = [
        float(item["input_tokens_actual"] - item.get("cached_input_tokens_actual", 0))
        for item in usage
        if item.get("input_tokens_actual") is not None
    ]
    return {
        "runs": len(runs),
        "passed": len(successful),
        "pass_rate": round(len(successful) / len(runs), 3) if runs else 0.0,
        "tokens_actual_mean": mean(tokens),
        "uncached_input_tokens_actual_mean": mean(uncached),
        "elapsed_seconds_mean": mean(elapsed),
        "model_calls_mean": mean(calls),
        "context_modes": mode_counts,
        "expected_modes": expected_modes,
        "mechanism_observed": all(mode_counts.get(name, 0) > 0 for name in expected_modes),
        "run_ids": [run.get("run_id") for run in runs],
    }


def interaction(cells: dict[str, dict], metric: str) -> float | None:
    values = [cells[key].get(metric) for key in ("00", "10", "01", "11")]
    if any(value is None for value in values):
        return None
    baseline, first, second, combined = values
    return round(first + second - baseline - combined, 3)


def markdown(result: dict) -> str:
    lines = [f"# {result['title']}", "", f"Factors: **{result['factors'][0]}** and **{result['factors'][1]}**.", ""]
    lines.extend([
        "| Cell | Flow | Passed | Actual tokens | Uncached input | Seconds | Model calls | Mechanism observed |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for key in ("00", "10", "01", "11"):
        cell = result["cells"][key]
        lines.append(
            f"| {key} | `{cell['flow']}` | {cell['passed']}/{cell['runs']} | "
            f"{cell['tokens_actual_mean']} | {cell['uncached_input_tokens_actual_mean']} | "
            f"{cell['elapsed_seconds_mean']} | {cell['model_calls_mean']} | {cell['mechanism_observed']} |"
        )
    lines.extend(["", "## Difference-of-differences interaction", ""])
    for metric, value in result["interaction"].items():
        lines.append(f"- `{metric}`: {value}")
    lines.extend(["", f"Verdict: **{result['verdict']}**", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", choices=sorted(STUDIES), required=True)
    parser.add_argument("--reports", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output path without extension")
    args = parser.parse_args()

    spec = STUDIES[args.study]
    runs: list[dict] = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        runs.extend(report.get("runs") or [])

    cells: dict[str, dict] = {}
    for key, flow in spec["cells"].items():
        selected = [run for run in runs if run.get("flow") == flow]
        cell = summarize_cell(selected, spec["expected_modes"].get(key, []))
        cell["flow"] = flow
        cells[key] = cell

    interactions = {
        metric: interaction(cells, metric)
        for metric in (
            "tokens_actual_mean",
            "uncached_input_tokens_actual_mean",
            "elapsed_seconds_mean",
            "model_calls_mean",
        )
    }
    all_correct = all(cell["runs"] and cell["pass_rate"] == 1.0 for cell in cells.values())
    all_triggered = all(cell["mechanism_observed"] for key, cell in cells.items() if key != "00")
    token_interaction = interactions["tokens_actual_mean"]
    single_effects_help = False
    combined_dominates = False
    token_values = [cells[key].get("tokens_actual_mean") for key in ("00", "10", "01", "11")]
    if not any(value is None for value in token_values):
        baseline, first, second, combined = token_values
        single_effects_help = first < baseline and second < baseline
        combined_dominates = combined < first and combined < second

    if not all_correct:
        verdict = "not product-safe: at least one cell lost correctness"
    elif not all_triggered:
        verdict = "safe coexistence, but not a synergy test: at least one enabled mechanism did not trigger"
    elif token_interaction is not None and token_interaction > 0 and single_effects_help and combined_dominates:
        verdict = "super-additive token synergy (1+1>1) with correctness preserved"
    elif token_interaction is not None and token_interaction > 0:
        verdict = "positive statistical interaction without practical 1+1>1 dominance"
    elif token_interaction is not None and token_interaction < 0:
        verdict = "negative/substitutive interaction; do not claim 1+1>1"
    else:
        verdict = "approximately additive interaction"

    result = {
        "schema": "ego.factorial-ablation.v1",
        "study": args.study,
        "title": spec["title"],
        "factors": spec["factors"],
        "reports": [str(path.resolve()) for path in args.reports],
        "cells": cells,
        "interaction": interactions,
        "all_correct": all_correct,
        "all_mechanisms_observed": all_triggered,
        "both_single_effects_help": single_effects_help,
        "combined_dominates_each_single": combined_dominates,
        "verdict": verdict,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all_correct else 2


if __name__ == "__main__":
    raise SystemExit(main())
