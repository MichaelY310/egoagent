"""Proof-carrying, budget-matched self-evolution research framework.

This module separates proposing a change, applying it experimentally, measuring
it on held-out tasks, and promoting it to trusted state.  A model's narrative
is never accepted as evidence by itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
import statistics
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ego_ir import EgoIRService


ARTIFACT_KINDS = {
    "none", "knowledge", "skill", "identity", "child_agent", "harness",
    "environment", "model_route", "memory_policy",
}
EXPERIMENT_VARIANTS = (
    "static", "matched_retry", "prompt_only", "knowledge_only", "skill_only",
    "structure_only", "full_evolution", "oracle",
)
DELEGATION_VARIANTS = (
    "direct", "ordinary_child", "result_only_child", "parallel_children",
    "persistent_child_knowledge", "evolving_child_harness",
)
SECRET_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,}]+)", re.I)
ARTIFACT_INTRUSION = {
    "none": 0.0,
    "knowledge": 0.10,
    "skill": 0.24,
    "memory_policy": 0.30,
    "identity": 0.38,
    "child_agent": 0.45,
    "harness": 0.58,
    "environment": 0.78,
    "model_route": 0.88,
}
TRUSTED_EVIDENCE_SOURCES = {
    "verified_test", "independent_replay", "deterministic_checker",
    "human_review", "signed_artifact",
}


class EvolutionProofError(ValueError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _walk_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_walk_text(child)}" for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return "\n".join(_walk_text(child) for child in value)
    return str(value or "")


def _bounded(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise EvolutionProofError(f"{name} must be between 0 and 1")
    return number


def validate_proposal(raw: Mapping[str, Any], *, heldout_ids: Iterable[str] = ()) -> dict[str, Any]:
    proposal = copy.deepcopy(dict(raw or {}))
    proposal.setdefault("format", "ego.evolution-proposal.v1")
    if proposal["format"] != "ego.evolution-proposal.v1":
        raise EvolutionProofError("unsupported evolution proposal format")
    proposal.setdefault("id", f"proposal_{uuid.uuid4().hex[:12]}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(proposal["id"])):
        raise EvolutionProofError("proposal id must be path safe")
    artifact = proposal.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("kind") not in ARTIFACT_KINDS:
        raise EvolutionProofError(f"artifact.kind must be one of {sorted(ARTIFACT_KINDS)}")
    if not str(proposal.get("target", "")).strip():
        raise EvolutionProofError("target is required")
    evidence = proposal.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise EvolutionProofError("at least one evidence record is required")
    for item in evidence:
        if not isinstance(item, dict) or not item.get("source") or not item.get("observation"):
            raise EvolutionProofError("each evidence record needs source and observation")
        if str(item.get("source")) in {"model_claim", "self_report"} and not item.get("artifact_ref"):
            raise EvolutionProofError("model self-report needs a real artifact_ref")
    evidence_assessment = assess_evolution_evidence(evidence)
    proposal["evidence"] = evidence_assessment["records"]
    proposal["evidence_assessment"] = evidence_assessment
    for required in ("scope", "change", "hypothesis", "evaluation", "cost", "rollback"):
        if not isinstance(proposal.get(required), dict):
            raise EvolutionProofError(f"{required} must be an object")
    hypothesis = proposal["hypothesis"]
    if not hypothesis.get("metric") or hypothesis.get("minimum_delta") is None:
        raise EvolutionProofError("hypothesis needs metric and minimum_delta")
    evaluation = proposal["evaluation"]
    for split in ("train", "validation", "heldout", "regression"):
        if not isinstance(evaluation.get(split), list) or not evaluation[split]:
            raise EvolutionProofError(f"evaluation.{split} must contain task ids")
    all_splits = [set(map(str, evaluation[name])) for name in ("train", "validation", "heldout")]
    if (all_splits[0] & all_splits[1]) or (all_splits[0] & all_splits[2]) or (all_splits[1] & all_splits[2]):
        raise EvolutionProofError("train, validation, and heldout task ids must be disjoint")
    proposal["confidence"] = _bounded(proposal.get("confidence", 0), "confidence")
    proposal["expected_reuse"] = _bounded(proposal.get("expected_reuse", 0), "expected_reuse")
    proposal["expected_benefit"] = _bounded(proposal.get("expected_benefit", 0), "expected_benefit")
    proposal["maintenance_cost"] = _bounded(proposal.get("maintenance_cost", 0), "maintenance_cost")
    proposal["regression_risk"] = _bounded(proposal.get("regression_risk", 0), "regression_risk")
    text = _walk_text(proposal)
    if SECRET_PATTERN.search(text):
        raise EvolutionProofError("proposal appears to contain a secret")
    hidden = set(map(str, heldout_ids)) | all_splits[2]
    proposal_only = _walk_text({"evidence": evidence, "change": proposal["change"], "hypothesis": hypothesis})
    leaked = sorted(task_id for task_id in hidden if task_id and task_id in proposal_only)
    # Listing held-out ids in the evaluation protocol is necessary; seeing
    # their instructions, expected outputs or ids in evidence/change is not.
    if leaked:
        raise EvolutionProofError(f"benchmark leakage detected in proposal evidence/change: {leaked}")
    proposal["validated_at"] = time.time()
    return proposal


def select_evolution_artifact(candidates: Iterable[Mapping[str, Any]], *, minimum_utility: float = 0.08) -> dict[str, Any]:
    """Rank model- or human-proposed artifacts using explicit economics.

    The selector does not infer a desired evolution from keywords.  It can
    choose no change, which makes spontaneous evolution observable instead of
    forcing a pre-scripted action.
    """
    ranked = []
    for raw in candidates:
        candidate = copy.deepcopy(dict(raw))
        kind = str(candidate.get("kind", "none"))
        if kind not in ARTIFACT_KINDS:
            raise EvolutionProofError(f"unknown candidate kind: {kind}")
        reuse = _bounded(candidate.get("expected_reuse", 0), "expected_reuse")
        benefit = _bounded(candidate.get("expected_benefit", 0), "expected_benefit")
        confidence = _bounded(candidate.get("confidence", 0), "confidence")
        implementation = _bounded(candidate.get("implementation_cost", 0), "implementation_cost")
        maintenance = _bounded(candidate.get("maintenance_cost", 0), "maintenance_cost")
        risk = _bounded(candidate.get("regression_risk", 0), "regression_risk")
        token_saving = _bounded(candidate.get("token_saving", 0), "token_saving")
        utility = reuse * benefit * confidence + 0.18 * token_saving - 0.22 * implementation - 0.18 * maintenance - 0.35 * risk
        candidate["utility"] = round(utility, 6)
        ranked.append(candidate)
    ranked.sort(key=lambda item: (item["utility"], item.get("confidence", 0)), reverse=True)
    if not ranked or ranked[0]["utility"] < minimum_utility:
        return {"kind": "none", "utility": 0.0, "reason": "No proposed change has positive risk-adjusted reuse value", "ranked": ranked}
    return {**ranked[0], "ranked": ranked}


def assess_evolution_evidence(
    evidence: Iterable[Mapping[str, Any]],
    *,
    minimum_independent_lineages: int = 2,
    require_trusted_anchor: bool = True,
) -> dict[str, Any]:
    """Assess whether experience is safe enough to become persistent instruction.

    Repeated observations from one origin remain one lineage.  This blocks the
    common trajectory-poisoning pattern where recurrence is manufactured by a
    single source while preserving a clear audit trail for legitimate evidence.
    """
    normalized = []
    for raw in evidence:
        item = copy.deepcopy(dict(raw or {}))
        source = str(item.get("source", "unknown")).strip().lower() or "unknown"
        trust = str(item.get("trust", "")).strip().lower()
        if trust not in {"trusted", "untrusted", "derived"}:
            trust = "trusted" if source in TRUSTED_EVIDENCE_SOURCES else "untrusted"
        lineage = str(
            item.get("lineage_id")
            or item.get("origin")
            or item.get("artifact_ref")
            or source
        ).strip()
        observation = str(item.get("observation", ""))
        digest = str(item.get("content_hash") or hashlib.sha256(observation.encode("utf-8")).hexdigest())
        item.update({"source": source, "trust": trust, "lineage_id": lineage, "content_hash": digest})
        normalized.append(item)
    lineages = {item["lineage_id"] for item in normalized if item["lineage_id"]}
    trusted = [item for item in normalized if item["trust"] == "trusted"]
    trusted_lineages = {item["lineage_id"] for item in trusted if item["lineage_id"]}
    hashes = {item["content_hash"] for item in normalized if item["content_hash"]}
    reasons = []
    if len(lineages) < max(1, int(minimum_independent_lineages)):
        reasons.append(
            f"only {len(lineages)} independent evidence lineage(s); "
            f"need {max(1, int(minimum_independent_lineages))}"
        )
    if require_trusted_anchor and not trusted:
        reasons.append("no trusted verifier, independent replay, human review, or signed artifact")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "records": normalized,
        "record_count": len(normalized),
        "independent_lineages": len(lineages),
        "trusted_records": len(trusted),
        "trusted_lineages": len(trusted_lineages),
        "unique_observations": len(hashes),
    }


def _paired_interval(values: list[float], *, seed: int, samples: int = 2000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    means = []
    for _ in range(max(200, int(samples))):
        means.append(statistics.fmean(values[rng.randrange(len(values))] for _ in values))
    means.sort()
    return means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]


def _empirical_candidate_report(
    raw: Mapping[str, Any],
    *,
    minimum_gain: float,
    noninferiority_margin: float,
    regression_tolerance: float,
    bootstrap_samples: int,
    require_provenance: bool,
) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(raw or {}))
    kind = str(candidate.get("kind", "none"))
    if kind not in ARTIFACT_KINDS:
        raise EvolutionProofError(f"unknown candidate kind: {kind}")
    measurements = [dict(item) for item in candidate.get("measurements", [])]
    if not measurements:
        raise EvolutionProofError(f"empirical candidate {kind!r} has no measurements")
    task_keys = []
    split_deltas: dict[str, list[float]] = {"validation": [], "heldout": [], "regression": []}
    relative_token_savings = []
    relative_cost_savings = []
    within_budget = True
    for item in measurements:
        split = str(item.get("split", ""))
        if split not in split_deltas:
            raise EvolutionProofError(f"measurement split must be validation, heldout, or regression: {split!r}")
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            raise EvolutionProofError("every empirical measurement needs task_id")
        key = (split, task_id)
        if key in task_keys:
            raise EvolutionProofError(f"duplicate empirical measurement: {key}")
        task_keys.append(key)
        baseline = dict(item.get("baseline") or {})
        evolved = dict(item.get("candidate") or {})
        delta = float(evolved.get("success", 0)) - float(baseline.get("success", 0))
        split_deltas[split].append(delta)
        before_tokens = max(1.0, float(baseline.get("tokens", 0) or 0))
        before_cost = max(1e-9, float(baseline.get("cost", 0) or 0))
        relative_token_savings.append((before_tokens - float(evolved.get("tokens", before_tokens))) / before_tokens)
        relative_cost_savings.append((before_cost - float(evolved.get("cost", before_cost))) / before_cost)
        within_budget = within_budget and bool(evolved.get("within_budget", True))
    if not split_deltas["validation"] or not split_deltas["heldout"]:
        raise EvolutionProofError(f"empirical candidate {kind!r} needs validation and heldout measurements")
    splits = {}
    for split, values in split_deltas.items():
        mean = statistics.fmean(values) if values else 0.0
        low, high = _paired_interval(
            values,
            seed=int(hashlib.sha256(f"{kind}:{split}".encode()).hexdigest()[:8], 16),
            samples=bootstrap_samples,
        )
        splits[split] = {"n": len(values), "mean_delta": mean, "ci95": [low, high]}
    evidence = assess_evolution_evidence(candidate.get("evidence", []))
    maintenance = _bounded(candidate.get("maintenance_cost", 0), "maintenance_cost")
    risk = _bounded(candidate.get("regression_risk", 0), "regression_risk")
    intrusion = ARTIFACT_INTRUSION[kind]
    heldout_lower = splits["heldout"]["ci95"][0]
    regression_mean = splits["regression"]["mean_delta"]
    eligibility = []
    if splits["validation"]["mean_delta"] < minimum_gain:
        eligibility.append("validation gain is below the requested minimum")
    if heldout_lower < -abs(noninferiority_margin):
        eligibility.append("heldout lower confidence bound violates non-inferiority")
    if split_deltas["regression"] and regression_mean < -abs(regression_tolerance):
        eligibility.append("regression tasks exceed the tolerated loss")
    if not within_budget:
        eligibility.append("one or more shadow runs exceeded the matched budget")
    if require_provenance and not evidence["eligible"]:
        eligibility.extend(f"evidence: {reason}" for reason in evidence["reasons"])
    token_saving = statistics.fmean(relative_token_savings)
    cost_saving = statistics.fmean(relative_cost_savings)
    utility = (
        0.40 * splits["validation"]["mean_delta"]
        + 0.60 * splits["heldout"]["mean_delta"]
        + 0.10 * token_saving
        + 0.08 * cost_saving
        - 0.10 * maintenance
        - 0.16 * risk
        - 0.06 * intrusion
    )
    return {
        **candidate,
        "kind": kind,
        "task_keys": [list(key) for key in sorted(task_keys)],
        "splits": splits,
        "token_saving": token_saving,
        "cost_saving": cost_saving,
        "intrusion": intrusion,
        "evidence_assessment": evidence,
        "within_budget": within_budget,
        "eligible": not eligibility,
        "ineligibility_reasons": eligibility,
        "empirical_utility": round(utility, 8),
    }


def select_empirical_evolution_artifact(
    candidates: Iterable[Mapping[str, Any]],
    *,
    minimum_gain: float = 0.0,
    noninferiority_margin: float = 0.02,
    regression_tolerance: float = 0.0,
    simplicity_epsilon: float = 0.02,
    bootstrap_samples: int = 2000,
    require_provenance: bool = True,
) -> dict[str, Any]:
    """Choose the least intrusive empirically sufficient evolution layer.

    All layers must be measured on the same paired shadow tasks.  Among
    statistically eligible candidates close to the best observed utility, the
    one-standard-error-style rule chooses the least intrusive artifact.  This
    makes over-evolution measurable instead of rewarding the largest patch.
    """
    reports = [
        _empirical_candidate_report(
            raw,
            minimum_gain=float(minimum_gain),
            noninferiority_margin=float(noninferiority_margin),
            regression_tolerance=float(regression_tolerance),
            bootstrap_samples=int(bootstrap_samples),
            require_provenance=bool(require_provenance),
        )
        for raw in candidates
    ]
    if not reports:
        return {"kind": "none", "reason": "No candidate layers were evaluated", "ranked": []}
    expected_tasks = reports[0]["task_keys"]
    mismatched = [item["kind"] for item in reports[1:] if item["task_keys"] != expected_tasks]
    if mismatched:
        raise EvolutionProofError(f"candidate layers were not evaluated on identical paired tasks: {mismatched}")
    ranked = sorted(reports, key=lambda item: item["empirical_utility"], reverse=True)
    eligible = [item for item in ranked if item["eligible"]]
    if not eligible:
        return {
            "kind": "none",
            "reason": "No evolution layer passed empirical, budget, regression, and provenance gates",
            "ranked": ranked,
        }
    best_utility = eligible[0]["empirical_utility"]
    near_best = [
        item for item in eligible
        if item["empirical_utility"] >= best_utility - abs(float(simplicity_epsilon))
    ]
    chosen = min(near_best, key=lambda item: (item["intrusion"], -item["empirical_utility"]))
    return {
        **chosen,
        "selection_rule": "matched-shadow-minimal-sufficient-v1",
        "best_utility": best_utility,
        "simplicity_epsilon": abs(float(simplicity_epsilon)),
        "reason": (
            f"Selected the least intrusive empirically sufficient layer among {len(near_best)} "
            "candidate(s) within the simplicity margin of the best utility"
        ),
        "ranked": ranked,
    }


@dataclass
class GovernancePolicy:
    allowed_kinds: set[str] = field(default_factory=lambda: set(ARTIFACT_KINDS))
    max_operations: int = 20
    max_changed_files: int = 20
    max_cost_increase: float = 0.25
    max_regression_risk: float = 0.35
    require_human_for: set[str] = field(default_factory=lambda: {"environment", "model_route"})
    require_signed_artifacts: bool = False
    require_evidence_integrity: bool = True
    minimum_independent_lineages: int = 2
    require_trusted_evidence_anchor: bool = True

    def inspect(self, proposal: Mapping[str, Any], *, human_approved: bool = False) -> dict[str, Any]:
        kind = proposal["artifact"]["kind"]
        reasons = []
        if kind not in self.allowed_kinds:
            reasons.append(f"artifact kind not allowed: {kind}")
        if kind in self.require_human_for and not human_approved:
            reasons.append(f"human approval required for {kind}")
        operations = proposal.get("change", {}).get("operations", [])
        files = proposal.get("change", {}).get("files", [])
        if len(operations) > self.max_operations:
            reasons.append("operation quota exceeded")
        if len(files) > self.max_changed_files:
            reasons.append("changed-file quota exceeded")
        if float(proposal.get("regression_risk", 0)) > self.max_regression_risk:
            reasons.append("regression risk exceeds policy")
        cost = proposal.get("cost", {})
        before, after = float(cost.get("before", 0)), float(cost.get("after", 0))
        if before > 0 and (after - before) / before > self.max_cost_increase:
            reasons.append("estimated cost increase exceeds policy")
        evidence = assess_evolution_evidence(
            proposal.get("evidence", []),
            minimum_independent_lineages=self.minimum_independent_lineages,
            require_trusted_anchor=self.require_trusted_evidence_anchor,
        )
        if self.require_evidence_integrity and kind != "none" and not evidence["eligible"]:
            reasons.extend(f"evidence integrity: {reason}" for reason in evidence["reasons"])
        return {
            "allowed": not reasons,
            "reasons": reasons,
            "human_approved": human_approved,
            "evidence_assessment": evidence,
        }


class EvolutionRepository:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve() / ".egoagent" / "evolution"

    def save(self, proposal: Mapping[str, Any], status: str = "experimental") -> dict[str, Any]:
        if status not in {"experimental", "trusted", "quarantine", "rejected"}:
            raise EvolutionProofError(f"unknown proposal status: {status}")
        value = copy.deepcopy(dict(proposal))
        value["status"] = status
        value["updated_at"] = time.time()
        _atomic_json(self.root / status / f"{value['id']}.json", value)
        return value

    def load(self, proposal_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(proposal_id)):
            raise EvolutionProofError("invalid proposal id")
        for status in ("experimental", "trusted", "quarantine", "rejected"):
            path = self.root / status / f"{proposal_id}.json"
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        raise EvolutionProofError(f"proposal not found: {proposal_id}")

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        statuses = [status] if status else ["experimental", "trusted", "quarantine", "rejected"]
        result = []
        for current in statuses:
            for path in (self.root / current).glob("*.json"):
                try:
                    result.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
        return sorted(result, key=lambda item: item.get("updated_at", 0), reverse=True)

    def move(self, proposal_id: str, status: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
        current = self.load(proposal_id)
        old_status = current.get("status", "experimental")
        current.setdefault("promotion_history", []).append({"from": old_status, "to": status, "at": time.time(), "evidence": copy.deepcopy(dict(evidence))})
        saved = self.save(current, status)
        old = self.root / old_status / f"{proposal_id}.json"
        new = self.root / status / f"{proposal_id}.json"
        if old != new:
            old.unlink(missing_ok=True)
        return saved


def aggregate_measurements(records: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    values = list(records)
    if not values:
        return {"success": 0.0, "tokens": 0.0, "parent_tokens": 0.0, "cost": 0.0, "latency": 0.0, "reuse": 0.0, "stability": 0.0}
    def mean(name: str) -> float:
        return statistics.fmean(float(item.get(name, 0)) for item in values)
    successes = [float(item.get("success", 0)) for item in values]
    return {
        "success": statistics.fmean(successes), "tokens": mean("tokens"), "parent_tokens": mean("parent_tokens"),
        "cost": mean("cost"), "latency": mean("latency"), "reuse": mean("reuse"),
        "stability": max(0.0, 1.0 - (statistics.pstdev(successes) if len(successes) > 1 else 0.0)),
    }


def fair_evolution_experiment(
    tasks: Mapping[str, Iterable[Mapping[str, Any]]],
    evaluator: Callable[[str, Mapping[str, Any], Mapping[str, float]], Mapping[str, Any]],
    *, variants: Iterable[str] = EXPERIMENT_VARIANTS,
    budget: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate all variants on identical disjoint tasks and budget caps."""
    budget = dict(budget or {"max_tokens": 20000, "max_cost": 1.0, "max_latency": 600})
    split_tasks = {name: [dict(task) for task in values] for name, values in tasks.items()}
    for name in ("train", "validation", "heldout"):
        if name not in split_tasks or not split_tasks[name]:
            raise EvolutionProofError(f"experiment needs non-empty {name} tasks")
    ids = [{str(task.get("id")) for task in split_tasks[name]} for name in ("train", "validation", "heldout")]
    if (ids[0] & ids[1]) or (ids[0] & ids[2]) or (ids[1] & ids[2]):
        raise EvolutionProofError("experiment task splits overlap")
    report = {"format": "ego.evolution-experiment.v1", "budget": budget, "variants": {}, "created_at": time.time()}
    for variant in variants:
        if variant not in EXPERIMENT_VARIANTS and variant not in DELEGATION_VARIANTS:
            raise EvolutionProofError(f"unknown experiment variant: {variant}")
        split_report = {}
        for split, cases in split_tasks.items():
            records = []
            for task in cases:
                measurement = dict(evaluator(variant, task, budget))
                measurement["task_id"] = task.get("id")
                measurement["within_budget"] = (
                    float(measurement.get("tokens", 0)) <= float(budget.get("max_tokens", math.inf))
                    and float(measurement.get("cost", 0)) <= float(budget.get("max_cost", math.inf))
                    and float(measurement.get("latency", 0)) <= float(budget.get("max_latency", math.inf))
                )
                if not measurement["within_budget"]:
                    measurement["success"] = 0.0
                records.append(measurement)
            split_report[split] = {"aggregate": aggregate_measurements(records), "records": records}
        report["variants"][variant] = split_report
    return report


def promotion_decision(proposal: Mapping[str, Any], baseline: Mapping[str, Any], candidate: Mapping[str, Any], *, policy: GovernancePolicy | None = None, human_approved: bool = False) -> dict[str, Any]:
    policy = policy or GovernancePolicy()
    governance = policy.inspect(proposal, human_approved=human_approved)
    reasons = list(governance["reasons"])
    minimum = float(proposal["hypothesis"].get("minimum_delta", 0))
    split_delta = {}
    for split in ("validation", "heldout"):
        before = float(baseline.get(split, {}).get("success", 0))
        after = float(candidate.get(split, {}).get("success", 0))
        split_delta[split] = after - before
        if split_delta[split] < minimum:
            reasons.append(f"{split} delta {split_delta[split]:.4f} is below {minimum:.4f}")
    regressions = candidate.get("regression", {})
    if not regressions.get("passed", False):
        reasons.append("regression suite failed")
    for split in ("validation", "heldout"):
        if not candidate.get(split, {}).get("within_budget", False):
            reasons.append(f"{split} exceeded the matched budget")
    accepted = not reasons
    return {
        "accepted": accepted, "decision": "promote" if accepted else "rollback",
        "reasons": reasons, "deltas": split_delta, "governance": governance,
        "confidence": proposal.get("confidence"), "evaluated_at": time.time(),
    }


class ProofEvolutionController:
    def __init__(self, project_root: Path | str, policy: GovernancePolicy | None = None):
        self.project_root = Path(project_root).resolve()
        self.repository = EvolutionRepository(self.project_root)
        self.policy = policy or GovernancePolicy()

    def register(self, proposal: Mapping[str, Any], *, heldout_ids: Iterable[str] = ()) -> dict[str, Any]:
        value = validate_proposal(proposal, heldout_ids=heldout_ids)
        governance = self.policy.inspect(value)
        value["governance"] = governance
        return self.repository.save(value, "experimental" if governance["allowed"] else "quarantine")

    def apply_experimental(self, proposal_id: str, *, human_approved: bool = False, dry_run: bool = False) -> dict[str, Any]:
        proposal = self.repository.load(proposal_id)
        governance = self.policy.inspect(proposal, human_approved=human_approved)
        if not governance["allowed"]:
            raise EvolutionProofError("governance rejected proposal: " + "; ".join(governance["reasons"]))
        kind = proposal["artifact"]["kind"]
        if kind == "none":
            return {"ok": True, "action": "no_change", "dry_run": dry_run}
        if kind == "harness":
            change = proposal["change"]
            result = EgoIRService(self.project_root).patch(
                proposal["target"], change.get("operations", []),
                expected_revision=change.get("expected_revision"), dry_run=dry_run,
                checks=change.get("checks", []), reason=proposal["hypothesis"].get("description", ""), actor="evolver",
            )
        elif kind in {"knowledge", "skill", "child_agent"} and proposal["change"].get("capability_pack"):
            from self_evolution.capability_evolution import CapabilityEvolutionService
            result = CapabilityEvolutionService(self.project_root).install(
                proposal["target"], proposal["change"]["capability_pack"], dry_run=dry_run,
                reason=proposal["hypothesis"].get("description", "proof evolution"),
            )
        else:
            raise EvolutionProofError(f"{kind} needs an explicit reviewed product adapter before it can be applied")
        proposal["application"] = {"result": result, "at": time.time(), "dry_run": dry_run}
        if not dry_run:
            self.repository.save(proposal, "experimental")
        return result

    def gate(self, proposal_id: str, baseline: Mapping[str, Any], candidate: Mapping[str, Any], *, human_approved: bool = False) -> dict[str, Any]:
        proposal = self.repository.load(proposal_id)
        decision = promotion_decision(proposal, baseline, candidate, policy=self.policy, human_approved=human_approved)
        proposal.setdefault("evaluations", []).append({"baseline": copy.deepcopy(dict(baseline)), "candidate": copy.deepcopy(dict(candidate)), "decision": decision})
        self.repository.save(proposal, "experimental")
        if decision["accepted"]:
            self.repository.move(proposal_id, "trusted", decision)
        else:
            application = proposal.get("application", {}).get("result", {})
            transaction = application.get("transaction_id")
            if transaction and proposal["artifact"]["kind"] == "harness":
                EgoIRService(self.project_root).rollback(transaction, expected_revision=application.get("revision"))
            elif transaction and proposal["artifact"]["kind"] in {"knowledge", "skill", "child_agent"}:
                from self_evolution.capability_evolution import CapabilityEvolutionService
                CapabilityEvolutionService(self.project_root).rollback(transaction)
            self.repository.move(proposal_id, "rejected", decision)
        return decision


def lifelong_metrics(phases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    phases = [copy.deepcopy(dict(item)) for item in phases]
    best: dict[str, float] = {}
    forgetting = []
    for phase in phases:
        scores = phase.get("task_scores", {})
        for task_id, raw_score in scores.items():
            score = float(raw_score)
            if task_id in best:
                forgetting.append(max(0.0, best[task_id] - score))
            best[task_id] = max(best.get(task_id, score), score)
    total_evolution_cost = sum(float(item.get("evolution_cost", 0)) for item in phases)
    reuse_benefit = sum(float(item.get("reuse_benefit", 0)) for item in phases)
    return {
        "phases": phases,
        "mean_forgetting": statistics.fmean(forgetting) if forgetting else 0.0,
        "worst_forgetting": max(forgetting, default=0.0),
        "evolution_amortization": (reuse_benefit / total_evolution_cost) if total_evolution_cost else (math.inf if reuse_benefit else 0.0),
        "recovery": statistics.fmean(float(item.get("recovery", 0)) for item in phases) if phases else 0.0,
        "negative_transfer": statistics.fmean(float(item.get("negative_transfer", 0)) for item in phases) if phases else 0.0,
    }
