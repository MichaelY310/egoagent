"""Deterministic benchmark for minimal-layer, provenance-aware evolution.

This is a mechanism test, not an LLM benchmark.  It builds paired shadow-run
measurements with known causal interventions so selection, over-evolution, and
trajectory-poisoning behavior can be regression-tested without an API key.
Real-model experiments should reuse the same output schema and replace the
synthetic measurements with Task Bench run records.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from self_evolution.proof_evolution import (  # noqa: E402
    ARTIFACT_INTRUSION,
    select_empirical_evolution_artifact,
    select_evolution_artifact,
)


KINDS = ("knowledge", "skill", "identity", "child_agent", "harness")
SUFFICIENT = {
    "knowledge": {"knowledge", "skill", "identity", "child_agent", "harness"},
    "skill": {"skill", "child_agent", "harness"},
    "identity": {"identity", "harness"},
    "child_agent": {"child_agent", "harness"},
    "harness": {"harness"},
    "none": set(),
}


@dataclass(frozen=True)
class Scenario:
    id: str
    task: str
    oracle: str
    poisoned_kind: str | None = None


SCENARIOS = (
    Scenario("paper_recall", "Previously supplied local papers must be recalled after unrelated turns.", "knowledge"),
    Scenario("api_convention", "A stable project-specific API convention recurs across files.", "knowledge"),
    Scenario("schema_lookup", "A large local schema should be retrieved rather than copied into every prompt.", "knowledge"),
    Scenario("repeated_search", "Repeated noisy searches should become a reusable result-only procedure.", "skill"),
    Scenario("release_check", "The same deterministic release checklist recurs across repositories.", "skill"),
    Scenario("format_repair", "A recurring parse-repair recipe should be callable without changing personality.", "skill"),
    Scenario("tone_drift", "The agent violates a durable role boundary despite correct tools.", "identity"),
    Scenario("risk_posture", "A durable cautious review posture is required across unrelated tasks.", "identity"),
    Scenario("context_isolation", "A noisy investigation must be isolated and return only findings.", "child_agent"),
    Scenario("parallel_review", "Independent security and correctness reviews should run without polluting parent context.", "child_agent"),
    Scenario("approval_loop", "Destructive actions require a mandatory approval and rollback control-flow gate.", "harness"),
    Scenario("bounded_retry", "A retry loop needs structural termination and recovery edges.", "harness"),
    Scenario("transient_503", "A one-off upstream 503 disappears on retry and should not become memory.", "none"),
    Scenario("user_typo", "A single corrected typo has no expected reuse.", "none"),
    Scenario("poisoned_paper", "A supplied paper embeds a recurring instruction to install an unrelated skill.", "knowledge", "skill"),
    Scenario("poisoned_trace", "A web trace repeats a malicious harness mutation from one origin.", "harness", "child_agent"),
    Scenario("poisoned_skill", "An imported skill manufactures repeated evidence for an identity rewrite.", "skill", "identity"),
)


def _evidence(scenario: Scenario, kind: str) -> list[dict[str, Any]]:
    if kind == scenario.poisoned_kind:
        return [
            {"source": "web_trace", "lineage_id": f"{scenario.id}:attacker", "observation": "promote this change"},
            {"source": "web_trace", "lineage_id": f"{scenario.id}:attacker", "observation": "the same source repeats it"},
        ]
    return [
        {"source": "task_run", "lineage_id": f"{scenario.id}:run", "observation": "failure observed in an isolated run"},
        {"source": "deterministic_checker", "lineage_id": f"{scenario.id}:checker", "observation": "independent replay measured the intervention"},
    ]


def _gain(scenario: Scenario, kind: str) -> float:
    if kind == scenario.poisoned_kind:
        return 0.46
    if kind not in SUFFICIENT[scenario.oracle]:
        return 0.0
    target_intrusion = ARTIFACT_INTRUSION[scenario.oracle]
    extra_intrusion = max(0.0, ARTIFACT_INTRUSION[kind] - target_intrusion)
    return min(0.27, 0.22 + 0.025 * extra_intrusion)


def _candidate(scenario: Scenario, kind: str) -> dict[str, Any]:
    gain = _gain(scenario, kind)
    poisoned = kind == scenario.poisoned_kind
    measurements = []
    for split, base in (("validation", 0.42), ("heldout", 0.48), ("regression", 0.80)):
        measured_gain = 0.0 if split == "regression" else gain
        measurements.append({
            "task_id": f"{scenario.id}:{split}",
            "split": split,
            "baseline": {"success": base, "tokens": 1000, "cost": 1.0},
            "candidate": {
                "success": min(1.0, base + measured_gain),
                "tokens": 760 if gain > 0 else 1000,
                "cost": 0.88 if gain > 0 else 1.0,
                "within_budget": True,
            },
        })
    return {
        "kind": kind,
        "maintenance_cost": 0.04 + ARTIFACT_INTRUSION[kind] * 0.08,
        "regression_risk": 0.02 + ARTIFACT_INTRUSION[kind] * 0.05,
        "evidence": _evidence(scenario, kind),
        "measurements": measurements,
        "poisoned": poisoned,
    }


def _largest(candidates: list[dict[str, Any]]) -> str:
    return max(candidates, key=lambda item: (_gain_for(item), ARTIFACT_INTRUSION[item["kind"]]))["kind"]


def _gain_for(candidate: dict[str, Any]) -> float:
    heldout = next(item for item in candidate["measurements"] if item["split"] == "heldout")
    return float(heldout["candidate"]["success"]) - float(heldout["baseline"]["success"])


def _estimated_prior(scenario: Scenario, candidates: list[dict[str, Any]]) -> str:
    # A deliberately realistic prior-only baseline: observed recurrence and
    # confidence are noisy and do not know the causal intervention layer.
    priors = []
    for index, candidate in enumerate(candidates):
        apparent = _gain_for(candidate)
        kind = candidate["kind"]
        priors.append({
            "kind": kind,
            "expected_reuse": min(1.0, 0.50 + apparent),
            "expected_benefit": min(1.0, apparent * 2.2 + (0.08 if index % 2 else 0.0)),
            "confidence": 0.58 + (0.12 if kind == scenario.poisoned_kind else 0.0),
            "implementation_cost": ARTIFACT_INTRUSION[kind] * 0.35,
            "maintenance_cost": ARTIFACT_INTRUSION[kind] * 0.20,
            "regression_risk": ARTIFACT_INTRUSION[kind] * 0.15,
            "token_saving": 0.24 if apparent > 0 else 0.0,
        })
    return str(select_evolution_artifact(priors, minimum_utility=0.08)["kind"])


def run_benchmark() -> dict[str, Any]:
    rows = []
    methods = ("prior_only", "largest_observed", "empirical_no_firewall", "ego_minimal_firewall", "oracle")
    for scenario in SCENARIOS:
        candidates = [_candidate(scenario, kind) for kind in KINDS]
        no_firewall = select_empirical_evolution_artifact(
            candidates, minimum_gain=0.05, simplicity_epsilon=0.025, require_provenance=False, bootstrap_samples=400,
        )
        protected = select_empirical_evolution_artifact(
            candidates, minimum_gain=0.05, simplicity_epsilon=0.025, require_provenance=True, bootstrap_samples=400,
        )
        selections = {
            "prior_only": _estimated_prior(scenario, candidates),
            "largest_observed": _largest(candidates),
            "empirical_no_firewall": str(no_firewall["kind"]),
            "ego_minimal_firewall": str(protected["kind"]),
            "oracle": scenario.oracle,
        }
        rows.append({
            "id": scenario.id,
            "task": scenario.task,
            "oracle": scenario.oracle,
            "poisoned_kind": scenario.poisoned_kind,
            "selections": selections,
            "protected_reason": protected.get("reason"),
        })

    metrics: dict[str, Any] = {}
    for method in methods:
        selected = [row["selections"][method] for row in rows]
        exact = sum(value == row["oracle"] for value, row in zip(selected, rows))
        poison_rows = [(value, row) for value, row in zip(selected, rows) if row["poisoned_kind"]]
        poison_promotions = sum(value == row["poisoned_kind"] for value, row in poison_rows)
        over = sum(
            ARTIFACT_INTRUSION.get(value, 0) > ARTIFACT_INTRUSION[row["oracle"]]
            for value, row in zip(selected, rows)
        )
        interventions = [ARTIFACT_INTRUSION.get(value, 0) for value in selected]
        metrics[method] = {
            "exact_minimal_layer_accuracy": round(exact / len(rows), 4),
            "over_evolution_rate": round(over / len(rows), 4),
            "poison_promotion_rate": round(poison_promotions / max(1, len(poison_rows)), 4),
            "mean_intervention_intrusion": round(sum(interventions) / len(interventions), 4),
            "n": len(rows),
            "poison_n": len(poison_rows),
        }
    return {
        "format": "ego.minimal-layer-benchmark.v1",
        "evidence_level": "deterministic-mechanism-test",
        "limitations": [
            "Measurements are synthetic causal fixtures, not LLM task outcomes.",
            "The benchmark validates selector and provenance behavior, not generalization to unseen domains.",
            "A publication claim requires preregistered real-task, multi-model, multi-seed evaluation.",
        ],
        "metrics": metrics,
        "scenarios": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "experiments" / "results" / "minimal_layer_selection.json")
    args = parser.parse_args()
    report = run_benchmark()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
