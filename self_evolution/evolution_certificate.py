"""Causal promotion certificates for multi-artifact EgoAgent updates.

The module consumes paired counterfactual measurements.  It never asks a model
whether its own update was useful: necessity, graft sufficiency, protected
behavior, portability and low-order interactions are computed deterministically.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import statistics
import time
from collections.abc import Iterable, Mapping
from typing import Any

from self_evolution.proof_evolution import EvolutionProofError, _paired_interval, assess_evolution_evidence


CERTIFICATE_FORMAT = "ego.evolution-certificate.v1"
ARTIFACT_KINDS = {
    "model", "identity", "knowledge", "skill", "child_agent", "harness",
    "environment", "runtime", "memory_policy", "model_route",
}


def _artifact(raw: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(raw or {}))
    artifact_id = str(value.get("id", "")).strip()
    kind = str(value.get("kind", "")).strip()
    if not artifact_id or not artifact_id.replace("_", "").replace("-", "").isalnum():
        raise EvolutionProofError("certificate artifact.id must be path safe")
    if kind not in ARTIFACT_KINDS:
        raise EvolutionProofError(f"certificate artifact.kind must be one of {sorted(ARTIFACT_KINDS)}")
    value["id"] = artifact_id
    value["kind"] = kind
    return value


def _normalize_records(records: Iterable[Mapping[str, Any]], artifact_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    duplicates: set[tuple[str, str, tuple[str, ...]]] = set()
    required_splits = {"validation", "heldout", "protected"}
    seen_splits: set[str] = set()
    task_variants: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    for raw in records:
        item = copy.deepcopy(dict(raw or {}))
        split = str(item.get("split", "")).strip()
        task_id = str(item.get("task_id", "")).strip()
        active = tuple(sorted(set(map(str, item.get("active_artifacts", [])))))
        if not task_id or split not in required_splits:
            raise EvolutionProofError("certificate measurement needs task_id and split validation/heldout/protected")
        unknown = sorted(set(active) - artifact_ids)
        if unknown:
            raise EvolutionProofError(f"measurement activates unknown artifacts: {unknown}")
        key = (split, task_id, active)
        if key in duplicates:
            raise EvolutionProofError(f"duplicate certificate measurement: {key}")
        duplicates.add(key)
        success = float(item.get("success", 0))
        if not math.isfinite(success) or success < 0 or success > 1:
            raise EvolutionProofError("certificate measurement success must be between 0 and 1")
        item.update({
            "split": split, "task_id": task_id, "active_artifacts": list(active),
            "success": success, "within_budget": item.get("within_budget", True) is not False,
            "activated": item.get("activated", True) is not False,
        })
        normalized.append(item)
        seen_splits.add(split)
        task_variants.setdefault((split, task_id), set()).add(active)
    missing_splits = sorted(required_splits - seen_splits)
    if missing_splits:
        raise EvolutionProofError(f"certificate measurements missing splits: {missing_splits}")
    task_ids = sorted({task_id for _split, task_id in task_variants})
    return normalized, task_ids


def _by_variant(records: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[tuple[str, str], dict[str, Any]]]:
    result: dict[tuple[str, ...], dict[tuple[str, str], dict[str, Any]]] = {}
    for item in records:
        variant = tuple(item["active_artifacts"])
        result.setdefault(variant, {})[(item["split"], item["task_id"])] = item
    return result


def _paired_effect(
    variants: dict[tuple[str, ...], dict[tuple[str, str], dict[str, Any]]],
    treatment: tuple[str, ...],
    control: tuple[str, ...],
    *,
    splits: set[str],
    seed_label: str,
    bootstrap_samples: int,
) -> dict[str, Any]:
    treatment_rows = variants.get(tuple(sorted(treatment)), {})
    control_rows = variants.get(tuple(sorted(control)), {})
    keys = sorted(key for key in set(treatment_rows) & set(control_rows) if key[0] in splits)
    deltas = [treatment_rows[key]["success"] - control_rows[key]["success"] for key in keys]
    seed = int(hashlib.sha256(seed_label.encode("utf-8")).hexdigest()[:8], 16)
    lower, upper = _paired_interval(deltas, seed=seed, samples=bootstrap_samples)
    return {
        "n": len(deltas),
        "mean_delta": statistics.fmean(deltas) if deltas else 0.0,
        "ci95": [lower, upper],
        "task_keys": [list(key) for key in keys],
    }


def issue_evolution_certificate(
    *,
    update_id: str,
    artifacts: Iterable[Mapping[str, Any]],
    measurements: Iterable[Mapping[str, Any]],
    evidence: Iterable[Mapping[str, Any]],
    activation: Mapping[str, int] | None = None,
    portability: Iterable[Mapping[str, Any]] = (),
    verifier_mutants: Iterable[Mapping[str, Any]] = (),
    minimum_total_gain: float = 0.03,
    necessity_margin: float = 0.01,
    portability_margin: float = 0.0,
    protected_margin: float = 0.02,
    mutation_threshold: float = 0.8,
    interaction_threshold: float = 0.03,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    """Issue an accept/abstain/reject certificate from paired interventions."""
    artifact_list = [_artifact(item) for item in artifacts]
    if not artifact_list:
        raise EvolutionProofError("certificate needs at least one changed artifact")
    artifact_ids = [item["id"] for item in artifact_list]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise EvolutionProofError("certificate artifacts must have unique ids")
    records, _task_ids = _normalize_records(measurements, set(artifact_ids))
    variants = _by_variant(records)
    full = tuple(sorted(artifact_ids))
    empty: tuple[str, ...] = ()
    required_variants = {empty, full}
    required_variants.update(tuple(item for item in full if item != artifact_id) for artifact_id in artifact_ids)
    missing_variants = [list(variant) for variant in required_variants if variant not in variants]

    total = _paired_effect(
        variants, full, empty, splits={"validation", "heldout"},
        seed_label=f"{update_id}:total", bootstrap_samples=bootstrap_samples,
    )
    validation_total = _paired_effect(
        variants, full, empty, splits={"validation"},
        seed_label=f"{update_id}:total:validation", bootstrap_samples=bootstrap_samples,
    )
    heldout_total = _paired_effect(
        variants, full, empty, splits={"heldout"},
        seed_label=f"{update_id}:total:heldout", bootstrap_samples=bootstrap_samples,
    )
    protected = _paired_effect(
        variants, full, empty, splits={"protected"},
        seed_label=f"{update_id}:protected", bootstrap_samples=bootstrap_samples,
    )
    necessity = {}
    for artifact_id in artifact_ids:
        knockout = tuple(item for item in full if item != artifact_id)
        necessity[artifact_id] = _paired_effect(
            variants, full, knockout, splits={"validation", "heldout"},
            seed_label=f"{update_id}:necessity:{artifact_id}", bootstrap_samples=bootstrap_samples,
        )

    interactions = []
    if len(artifact_ids) > 1:
        total_mean = total["mean_delta"]
        for left, right in itertools.combinations(artifact_ids, 2):
            coalition = tuple(sorted((left, right)))
            if coalition not in variants:
                continue
            left_effect = _paired_effect(variants, (left,), empty, splits={"validation", "heldout"}, seed_label=f"{update_id}:{left}", bootstrap_samples=bootstrap_samples)
            right_effect = _paired_effect(variants, (right,), empty, splits={"validation", "heldout"}, seed_label=f"{update_id}:{right}", bootstrap_samples=bootstrap_samples)
            pair_effect = _paired_effect(variants, coalition, empty, splits={"validation", "heldout"}, seed_label=f"{update_id}:{left}+{right}", bootstrap_samples=bootstrap_samples)
            synergy = pair_effect["mean_delta"] - left_effect["mean_delta"] - right_effect["mean_delta"]
            if abs(synergy) >= abs(interaction_threshold):
                interactions.append({"artifacts": [left, right], "synergy": synergy, "pair_effect": pair_effect, "fraction_of_total": synergy / total_mean if total_mean else 0.0})

    activation_counts = {artifact_id: int((activation or {}).get(artifact_id, 0)) for artifact_id in artifact_ids}
    activation_ok = all(count > 0 for count in activation_counts.values()) and all(
        item.get("activated", True) for item in variants.get(full, {}).values()
    )
    evidence_report = assess_evolution_evidence(evidence)

    portability_rows = [copy.deepcopy(dict(item)) for item in portability]
    portability_deltas = []
    for item in portability_rows:
        before = float(item.get("baseline", {}).get("success", 0))
        after = float(item.get("candidate", {}).get("success", 0))
        item["delta"] = after - before
        portability_deltas.append(item["delta"])
    portability_low, portability_high = _paired_interval(
        portability_deltas,
        seed=int(hashlib.sha256(f"{update_id}:portability".encode()).hexdigest()[:8], 16),
        samples=bootstrap_samples,
    )
    portability_report = {
        "n": len(portability_rows), "mean_delta": statistics.fmean(portability_deltas) if portability_deltas else 0.0,
        "ci95": [portability_low, portability_high], "records": portability_rows,
    }

    mutants = [copy.deepcopy(dict(item)) for item in verifier_mutants]
    relevant = [item for item in mutants if item.get("relevant", True) is not False]
    killed = [item for item in relevant if item.get("killed") is True]
    mutation_report = {
        "relevant": len(relevant), "killed": len(killed),
        "score": len(killed) / len(relevant) if relevant else 0.0,
        "survivors": [item.get("id") for item in relevant if item.get("killed") is not True],
    }

    hard_failures = []
    abstentions = []
    if missing_variants:
        abstentions.append(f"missing counterfactual variants: {missing_variants}")
    if validation_total["n"] == 0 or validation_total["ci95"][0] < float(minimum_total_gain):
        hard_failures.append("validation gain is not causally established")
    if heldout_total["n"] == 0 or heldout_total["ci95"][0] < float(minimum_total_gain):
        hard_failures.append("sealed heldout gain is not causally established")
    if protected["n"] == 0 or protected["ci95"][0] < -abs(float(protected_margin)):
        hard_failures.append("protected distribution violates non-interference margin")
    if not activation_ok:
        hard_failures.append("one or more changed artifacts did not activate")
    if not evidence_report["eligible"]:
        hard_failures.extend(f"evidence: {reason}" for reason in evidence_report["reasons"])
    if not portability_rows:
        abstentions.append("no fresh-identity/model/harness graft evidence")
    elif portability_report["ci95"][0] < float(portability_margin):
        hard_failures.append("portable graft is not non-inferior")
    if not relevant:
        abstentions.append("no relevant semantic verifier mutants")
    elif mutation_report["score"] < float(mutation_threshold):
        hard_failures.append("verifier mutation score is below threshold")

    optional_artifacts = [artifact_id for artifact_id, report in necessity.items() if report["n"] and report["ci95"][0] <= float(necessity_margin)]
    if optional_artifacts:
        hard_failures.append(f"update contains non-necessary artifacts: {optional_artifacts}")
    all_within_budget = all(item["within_budget"] for item in records)
    if not all_within_budget:
        hard_failures.append("one or more counterfactual runs exceeded the matched budget")

    decision = "reject" if hard_failures else "abstain" if abstentions else "accept"
    certificate = {
        "format": CERTIFICATE_FORMAT,
        "update_id": str(update_id),
        "artifact_set": artifact_list,
        "decision": decision,
        "causal_effects": {
            "total": total,
            "validation": validation_total,
            "heldout": heldout_total,
            "necessity": necessity,
            "interactions": interactions,
        },
        "activation": {"counts": activation_counts, "passed": activation_ok},
        "portability": portability_report,
        "noninterference": protected,
        "verifier_mutation_score": mutation_report,
        "evidence_assessment": evidence_report,
        "matched_budget": all_within_budget,
        "missing_variants": missing_variants,
        "reasons": hard_failures + abstentions,
        "issued_at": time.time(),
    }
    canonical = json.dumps(certificate, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    certificate["certificate_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return certificate
