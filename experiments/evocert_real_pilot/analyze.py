"""Frozen analysis for the EvoCert real-task pilot."""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from pathlib import Path
from typing import Any, Iterable


COMPONENTS = ("I", "K", "F")
VARIANTS = ("none", "I", "K", "F", "IK", "IF", "KF", "IKF")


def canonical_variant(active: Iterable[str]) -> str:
    selected = {str(item).upper() for item in active}
    unknown = selected - set(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown components: {sorted(unknown)}")
    return "".join(item for item in COMPONENTS if item in selected) or "none"


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _cells(rows: list[dict[str, Any]], split: str, variant: str) -> list[dict[str, Any]]:
    return [
        row[variant]
        for row in rows
        if row.get("split") == split and isinstance(row.get(variant), dict)
    ]


def _rate(rows: list[dict[str, Any]], split: str, variant: str) -> float:
    return _mean([float(cell.get("success", 0.0)) for cell in _cells(rows, split, variant)])


def _tokens(rows: list[dict[str, Any]], split: str, variant: str) -> float:
    return _mean([float(cell.get("tokens", 0.0)) for cell in _cells(rows, split, variant)])


def _effect(rates: dict[str, float], additions: tuple[str, ...], background: tuple[str, ...] = ()) -> float:
    """Finite difference for ``additions`` over a disjoint background."""
    if set(additions) & set(background):
        raise ValueError("additions and background must be disjoint")
    total = 0.0
    for size in range(len(additions) + 1):
        for subset in itertools.combinations(additions, size):
            active = tuple(background) + tuple(subset)
            sign = -1.0 if (len(additions) - size) % 2 else 1.0
            total += sign * rates[canonical_variant(active)]
    return total


def analyze_family(family: dict[str, Any]) -> dict[str, Any]:
    rows = list(family.get("rows") or [])
    rates = {
        split: {variant: _rate(rows, split, variant) for variant in VARIANTS}
        for split in ("validation", "heldout", "protected")
    }
    tokens = {
        split: {variant: _tokens(rows, split, variant) for variant in VARIANTS}
        for split in ("validation", "heldout", "protected")
    }
    heldout = rates["heldout"]
    protected = rates["protected"]
    interactions: dict[str, float] = {}
    for left, right in itertools.combinations(COMPONENTS, 2):
        remaining = tuple(item for item in COMPONENTS if item not in {left, right})
        interactions[left + right] = _effect(heldout, (left, right))
        interactions[left + right + "|" + "".join(remaining)] = _effect(
            heldout, (left, right), remaining
        )
    interactions["IKF"] = _effect(heldout, COMPONENTS)

    protected_floor = protected["none"]
    eligible = [
        variant
        for variant in VARIANTS
        if protected[variant] >= protected_floor
    ]
    best_success = max((heldout[item] for item in eligible), default=heldout["none"])
    best = [item for item in eligible if heldout[item] == best_success]
    best.sort(
        key=lambda item: (
            0 if item == "none" else len(item),
            tokens["heldout"][item],
            VARIANTS.index(item),
        )
    )
    oracle = best[0] if best else "none"

    validation_promotes_full = rates["validation"]["IKF"] > rates["validation"]["none"]
    heldout_promotes_full = heldout["IKF"] > heldout["none"]
    seal_promotes_full = heldout_promotes_full and protected["IKF"] >= protected["none"]
    loo_necessary = {
        item: heldout["IKF"] > heldout[canonical_variant(set(COMPONENTS) - {item})]
        for item in COMPONENTS
    }
    loo_promotes_full = seal_promotes_full and all(loo_necessary.values())
    full_is_oracle = oracle == "IKF"
    decisions = {
        "validation_only_promotes_IKF": validation_promotes_full,
        "heldout_promotes_IKF": heldout_promotes_full,
        "seal_style_promotes_IKF": seal_promotes_full,
        "leave_one_out_promotes_IKF": loo_promotes_full,
        "factorial_oracle": oracle,
        "IKF_is_minimal_oracle": full_is_oracle,
        "unnecessary_IKF_admission": {
            "validation_only": validation_promotes_full and not full_is_oracle,
            "heldout": heldout_promotes_full and not full_is_oracle,
            "seal_style": seal_promotes_full and not full_is_oracle,
            "leave_one_out": loo_promotes_full and not full_is_oracle,
        },
    }

    all_cells = [row[item] for row in rows for item in VARIANTS if isinstance(row.get(item), dict)]
    bad_states = {"error", "timeout", "stopped"}
    runtime_errors = sum(
        1 for cell in all_cells
        if cell.get("status") in bad_states or cell.get("runtime_error")
    )
    knowledge_runs = [
        row[item]
        for row in rows
        for item in ("K", "IK", "KF", "IKF")
        if isinstance(row.get(item), dict)
    ]
    knowledge_activation = _mean([
        1.0 if (cell.get("activation") or {}).get("K") else 0.0
        for cell in knowledge_runs
    ])
    return {
        "family": family.get("family"),
        "rates": rates,
        "mean_tokens": tokens,
        "interactions": interactions,
        "decisions": decisions,
        "leave_one_out_necessary": loo_necessary,
        "knowledge_activation_rate": knowledge_activation,
        "runtime_error_rate": runtime_errors / len(all_cells) if all_cells else 1.0,
        "n_cells": len(all_cells),
    }


def analyze_report(report: dict[str, Any]) -> dict[str, Any]:
    families = [analyze_family(item) for item in report.get("families") or []]
    interaction_signal = [
        item
        for family in families
        for item in family["interactions"].values()
        if abs(float(item)) >= 0.25
    ]
    disagreements = sum(
        1
        for family in families
        if any(family["decisions"]["unnecessary_IKF_admission"].values())
    )
    runtime_error_rate = _mean([item["runtime_error_rate"] for item in families])
    all_zero = bool(families) and all(
        all(value == 0 for value in family["rates"]["heldout"].values())
        for family in families
    )
    knowledge_never_activated = bool(families) and all(
        family["knowledge_activation_rate"] == 0 for family in families
    )
    quality_gate = {
        "all_heldout_zero": all_zero,
        "interaction_signal_count": len(interaction_signal),
        "families_with_admission_disagreement": disagreements,
        "mean_runtime_error_rate": runtime_error_rate,
        "knowledge_never_activated": knowledge_never_activated,
    }
    quality_gate["proceed_to_repetition_2"] = (
        not all_zero
        and runtime_error_rate <= 0.10
        and bool(interaction_signal or disagreements)
    )
    quality_gate["stop_direction"] = (
        all_zero
        or runtime_error_rate > 0.20
        or (not interaction_signal and disagreements == 0)
        or knowledge_never_activated
    )
    return {
        "format": "ego.evocert-real-pilot-analysis.v1",
        "source_run": report.get("stamp"),
        "families": families,
        "quality_gate": quality_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = analyze_report(report)
    destination = args.output or args.report.with_name("analysis.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["quality_gate"], ensure_ascii=False, indent=2))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
