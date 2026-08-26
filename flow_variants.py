"""Validated, auditable transformations for EgoAgent Flow configurations.

Models may *propose* these typed operations, but this module is the capability
boundary that applies them to a copy and validates the complete graph.  It is
deliberately domain-neutral: ARC, coding and research Flows use the same small
operation vocabulary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from node_registry import canonical_node_op, get_node_definition
from pipeline_schema import validate_pipeline


class FlowVariantError(ValueError):
    """A proposed Flow transformation is unsafe or invalid."""


_PART = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_proposal_evidence(
    proposal: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    required: bool = True,
) -> list[dict[str, Any]]:
    """Verify model-authored causal predicates against measured run data."""

    references = proposal.get("evidence_refs", []) if isinstance(proposal, Mapping) else []
    if not isinstance(references, list) or (required and not references):
        raise FlowVariantError("proposal requires at least one machine-verifiable evidence_ref")
    verified: list[dict[str, Any]] = []
    operators = {
        "eq": lambda actual, expected: actual == expected,
        "ne": lambda actual, expected: actual != expected,
        "gt": lambda actual, expected: actual > expected,
        "gte": lambda actual, expected: actual >= expected,
        "lt": lambda actual, expected: actual < expected,
        "lte": lambda actual, expected: actual <= expected,
        "in": lambda actual, expected: actual in expected,
    }
    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            raise FlowVariantError(f"evidence_ref {index} is not an object")
        path = str(reference.get("path", "")).strip()
        operator = str(reference.get("operator", "eq")).strip().lower()
        if not path or operator not in operators or "value" not in reference:
            raise FlowVariantError(
                f"evidence_ref {index} requires path, operator ({sorted(operators)}), and value"
            )
        actual: Any = evidence
        for part in path.split("."):
            if not isinstance(actual, Mapping) or part not in actual:
                raise FlowVariantError(f"evidence_ref {index} points to missing path {path!r}")
            actual = actual[part]
        expected = reference["value"]
        try:
            satisfied = bool(operators[operator](actual, expected))
        except (TypeError, ValueError) as error:
            raise FlowVariantError(
                f"evidence_ref {index} cannot compare {actual!r} {operator} {expected!r}"
            ) from error
        if not satisfied:
            raise FlowVariantError(
                f"evidence_ref {index} is contradicted by measurements: "
                f"{path} is {actual!r}, expected {operator} {expected!r}"
            )
        verified.append({
            "path": path,
            "operator": operator,
            "value": copy.deepcopy(expected),
            "actual": copy.deepcopy(actual),
        })
    return verified


def flow_digest(config: Mapping[str, Any]) -> str:
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parts(path: str) -> list[str]:
    parts = str(path or "").split(".")
    if not parts or any(not _PART.fullmatch(part) for part in parts):
        raise FlowVariantError(f"invalid dotted path: {path!r}")
    return parts


def _allowed(path: str, prefixes: Iterable[str] | None) -> bool:
    declared = [str(item).rstrip(".") for item in (prefixes or []) if str(item).strip()]
    return not declared or any(path == prefix or path.startswith(prefix + ".") for prefix in declared)


def _container(root: dict[str, Any], path: str) -> tuple[dict[str, Any], str]:
    parts = _parts(path)
    current: Any = root
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise FlowVariantError(f"path does not exist: {path!r}")
        current = current[part]
    if not isinstance(current, dict):
        raise FlowVariantError(f"path parent is not an object: {path!r}")
    return current, parts[-1]


def _nodes(config: dict[str, Any]) -> dict[str, Any]:
    try:
        nodes = config["pipeline"]["nodes"]
    except (KeyError, TypeError) as error:
        raise FlowVariantError("base config has no pipeline.nodes object") from error
    if not isinstance(nodes, dict):
        raise FlowVariantError("pipeline.nodes must be an object")
    return nodes


def _validate_inserted_node_contracts(
    candidate: Mapping[str, Any],
    inserted_node_ids: Iterable[str],
) -> None:
    """Reject graph-shaped candidates whose new nodes cannot emit their edges.

    The repository-wide schema intentionally remains backward compatible with
    older hand-authored Flows.  Model-authored mutations need a stricter gate:
    otherwise a graph can be topologically valid while a condition waits for
    an impossible event or a detached Tool silently reuses no tool calls.
    """

    nodes = candidate.get("pipeline", {}).get("nodes", {})
    for node_id in inserted_node_ids:
        node = nodes.get(node_id, {})
        operation = canonical_node_op(node.get("op", ""))
        definition = get_node_definition(operation)
        if definition is None:
            raise FlowVariantError(f"inserted node {node_id!r} has no registered contract")
        emitted = set(definition.events) | {"default"}
        edge_conditions = {
            str(edge.get("condition", "default"))
            for edge in node.get("edges", [])
            if isinstance(edge, Mapping)
        }
        impossible = sorted(edge_conditions - emitted)
        if impossible:
            raise FlowVariantError(
                f"inserted {operation} node {node_id!r} waits for events it cannot emit: {impossible}; "
                f"declared events are {sorted(definition.events)}"
            )
        if operation == "条件":
            inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), Mapping) else {}
            if node.get("condition", node.get("expression")) is None and "value" not in inputs:
                raise FlowVariantError(
                    f"inserted condition node {node_id!r} requires condition/expression or inputs.value"
                )
        if operation == "工具":
            inputs = node.get("inputs", {}) if isinstance(node.get("inputs", {}), Mapping) else {}
            predecessors = [
                (parent_id, canonical_node_op(parent.get("op", "")))
                for parent_id, parent in nodes.items()
                if any(
                    isinstance(edge, Mapping) and edge.get("to") == node_id
                    for edge in parent.get("edges", [])
                )
            ]
            produces_calls = any(parent_op in {"Agent", "工具审查"} for _, parent_op in predecessors)
            if "tool_calls" not in inputs and not produces_calls:
                raise FlowVariantError(
                    f"inserted tool node {node_id!r} has no explicit tool_calls input and no Agent/工具审查 predecessor"
                )


def apply_flow_variant(
    base_config: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    allowed_paths: Iterable[str] | None = None,
    max_operations: int = 12,
) -> dict[str, Any]:
    """Apply typed operations atomically and validate the resulting Flow.

    Supported operations are ``set_field``, ``insert_node_on_edge``,
    ``remove_node_and_bypass`` and ``redirect_edge``.  A caller may restrict
    every mutation with dotted-path prefixes.  No input object is mutated.
    """

    if not isinstance(base_config, Mapping) or not isinstance(proposal, Mapping):
        raise FlowVariantError("base_config and proposal must be objects")
    operations = proposal.get("operations", [])
    if not isinstance(operations, list) or not operations:
        raise FlowVariantError("proposal.operations must be a non-empty list")
    if len(operations) > max(1, int(max_operations)):
        raise FlowVariantError(f"proposal exceeds max_operations={max_operations}")

    candidate = copy.deepcopy(dict(base_config))
    audit: list[dict[str, Any]] = []
    inserted_node_ids: list[str] = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, Mapping):
            raise FlowVariantError(f"operation {index} is not an object")
        operation = str(raw.get("op", ""))
        if operation == "set_field":
            path = str(raw.get("path", ""))
            if not _allowed(path, allowed_paths):
                raise FlowVariantError(f"path is outside the declared mutation surface: {path}")
            parent, key = _container(candidate, path)
            if key not in parent and not bool(raw.get("allow_create", False)):
                raise FlowVariantError(f"set_field target does not exist: {path}")
            before = copy.deepcopy(parent.get(key))
            parent[key] = copy.deepcopy(raw.get("value"))
            if before == parent[key]:
                raise FlowVariantError(f"set_field operation {index} is a no-op: {path}")
            audit.append({"op": operation, "path": path, "before": before, "after": copy.deepcopy(parent[key])})
            continue

        nodes = _nodes(candidate)
        if operation == "remove_node_and_bypass":
            node_id = str(raw.get("node_id", ""))
            node_path = f"pipeline.nodes.{node_id}"
            if not _allowed(node_path, allowed_paths):
                raise FlowVariantError(f"removed node is outside the declared mutation surface: {node_id}")
            if node_id not in nodes or candidate.get("pipeline", {}).get("start") == node_id:
                raise FlowVariantError(f"cannot remove unknown or start node: {node_id}")
            outgoing = nodes[node_id].get("edges", [])
            bypass_condition = str(raw.get("bypass_condition", "default"))
            successors = [edge.get("to") for edge in outgoing if str(edge.get("condition", "default")) == bypass_condition]
            if len(successors) != 1 or successors[0] not in nodes:
                raise FlowVariantError(f"node {node_id} has no unique valid bypass edge")
            for parent in nodes.values():
                for edge in parent.get("edges", []):
                    if edge.get("to") == node_id:
                        edge["to"] = successors[0]
            del nodes[node_id]
            audit.append({"op": operation, "node_id": node_id, "bypass_to": successors[0]})
            continue

        source_id = str(raw.get("source", ""))
        condition = str(raw.get("condition", "default"))
        source_path = f"pipeline.nodes.{source_id}"
        if not _allowed(source_path, allowed_paths):
            raise FlowVariantError(f"source is outside the declared mutation surface: {source_id}")
        if source_id not in nodes:
            raise FlowVariantError(f"unknown source node: {source_id}")
        edges = nodes[source_id].setdefault("edges", [])
        matching = [edge for edge in edges if str(edge.get("condition", "default")) == condition]

        if operation == "redirect_edge":
            if len(matching) != 1:
                raise FlowVariantError(f"redirect_edge needs exactly one {source_id}:{condition} edge")
            target = str(raw.get("target", ""))
            if target not in nodes:
                raise FlowVariantError(f"unknown redirect target: {target}")
            before = matching[0].get("to")
            if before == target:
                raise FlowVariantError(
                    f"redirect_edge operation {index} is a no-op: {source_id}:{condition}"
                )
            matching[0]["to"] = target
            audit.append({"op": operation, "source": source_id, "condition": condition, "before": before, "after": target})
        elif operation == "insert_node_on_edge":
            if len(matching) != 1:
                raise FlowVariantError(f"insert_node_on_edge needs exactly one {source_id}:{condition} edge")
            node_id = str(raw.get("node_id", ""))
            node_path = f"pipeline.nodes.{node_id}"
            if not _PART.fullmatch(node_id) or node_id in nodes:
                raise FlowVariantError(f"invalid or duplicate inserted node id: {node_id!r}")
            if not _allowed(node_path, allowed_paths):
                raise FlowVariantError(f"inserted node is outside the declared mutation surface: {node_id}")
            node = copy.deepcopy(raw.get("node"))
            if not isinstance(node, dict) or not node.get("op"):
                raise FlowVariantError("insert_node_on_edge requires a node object with op")
            previous_target = str(matching[0].get("to", ""))
            node.setdefault("id", node_id)
            node.setdefault("edges", [{"condition": "default", "to": previous_target}])
            nodes[node_id] = node
            matching[0]["to"] = node_id
            inserted_node_ids.append(node_id)
            audit.append({"op": operation, "source": source_id, "condition": condition, "node_id": node_id, "previous_target": previous_target})
        else:
            raise FlowVariantError(f"unsupported Flow operation: {operation!r}")

    errors = validate_pipeline(candidate.get("pipeline", {}))
    if errors:
        raise FlowVariantError("candidate Flow failed validation: " + "; ".join(errors))
    _validate_inserted_node_contracts(candidate, inserted_node_ids)
    if flow_digest(candidate) == flow_digest(base_config):
        raise FlowVariantError("candidate Flow is identical to its base")
    return {
        "config": candidate,
        "base_digest": flow_digest(base_config),
        "candidate_digest": flow_digest(candidate),
        "operations": audit,
        "proposal": copy.deepcopy(dict(proposal)),
    }


def proposal_signature(proposal: Mapping[str, Any]) -> str:
    """Canonical signature used to deduplicate model-authored proposals."""

    operations = proposal.get("operations", []) if isinstance(proposal, Mapping) else []
    return hashlib.sha256(
        json.dumps(operations, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _proposal_features(proposal: Mapping[str, Any]) -> set[str]:
    features: set[str] = set()
    for operation in proposal.get("operations", []):
        if not isinstance(operation, Mapping):
            continue
        for key in ("op", "path", "source", "condition", "target", "node_id"):
            if key in operation:
                features.add(f"{key}:{operation[key]}")
        if "value" in operation:
            features.add(
                "value:" + json.dumps(operation["value"], ensure_ascii=False, sort_keys=True, default=str)
            )
        if "node" in operation:
            node = operation.get("node")
            if isinstance(node, Mapping):
                features.add(f"node.op:{node.get('op')}")
    return features


def build_flow_variant_population(
    base_config: Mapping[str, Any],
    proposals: Iterable[Mapping[str, Any]],
    *,
    allowed_paths: Iterable[str] | None = None,
    max_operations: int = 12,
    max_candidates: int = 6,
    min_novelty: float = 0.12,
    evaluation_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and retain a small, auditable set of distinct candidates."""

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    digests: set[str] = set()
    signatures: set[str] = set()
    feature_sets: list[set[str]] = []
    for index, proposal in enumerate(proposals):
        if len(accepted) >= max(1, int(max_candidates)):
            rejected.append({"index": index, "reason": "population capacity reached"})
            continue
        signature = proposal_signature(proposal)
        if signature in signatures:
            rejected.append({"index": index, "reason": "duplicate proposal signature"})
            continue
        try:
            verified_evidence = (
                validate_proposal_evidence(proposal, evaluation_evidence)
                if evaluation_evidence is not None
                else []
            )
            variant = apply_flow_variant(
                base_config,
                proposal,
                allowed_paths=allowed_paths,
                max_operations=max_operations,
            )
        except (FlowVariantError, TypeError, ValueError) as error:
            rejected.append({"index": index, "reason": str(error)})
            continue
        if variant["candidate_digest"] in digests:
            rejected.append({"index": index, "reason": "duplicate candidate digest"})
            continue
        features = _proposal_features(proposal)
        similarities = []
        for previous in feature_sets:
            union = features | previous
            similarities.append(len(features & previous) / max(1, len(union)))
        novelty = 1.0 - max(similarities, default=0.0)
        if feature_sets and novelty < max(0.0, min(1.0, float(min_novelty))):
            rejected.append({
                "index": index,
                "reason": "proposal is too similar to an accepted candidate",
                "novelty": round(novelty, 6),
            })
            continue
        signatures.add(signature)
        digests.add(variant["candidate_digest"])
        feature_sets.append(features)
        accepted.append({
            **variant,
            "verified_evidence": verified_evidence,
            "proposal_signature": signature,
            "novelty": round(novelty, 6),
            "source_index": index,
        })
    return {"accepted": accepted, "rejected": rejected}


def write_flow_variant(result: Mapping[str, Any], output_path: str | Path) -> Path:
    """Atomically persist a previously validated candidate configuration."""

    config = result.get("config")
    if not isinstance(config, Mapping):
        raise FlowVariantError("variant result has no config object")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def flow_promotion_decision(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    primary_metrics: Iterable[str],
    cost_metrics: Iterable[str] = (),
    cost_regression_tolerance: float = 0.05,
    heldout_verified: bool = False,
) -> dict[str, Any]:
    """Gate a candidate using real metrics, with higher primary and lower cost.

    Primary metrics are compared lexicographically in the caller-declared
    order.  Tied candidates cannot trade a material efficiency regression for
    a self-reported qualitative benefit, and no candidate is promoted without
    independent heldout evidence.
    """

    primary = list(primary_metrics)
    costs = list(cost_metrics)
    if not primary:
        raise FlowVariantError("promotion requires at least one primary metric")
    baseline_primary = tuple(float(baseline.get(key, 0) or 0) for key in primary)
    candidate_primary = tuple(float(candidate.get(key, 0) or 0) for key in primary)
    cost_regressions = []
    for key in costs:
        before = float(baseline.get(key, 0) or 0)
        after = float(candidate.get(key, 0) or 0)
        allowed = before * (1 + max(0.0, float(cost_regression_tolerance)))
        if after > allowed:
            cost_regressions.append({"metric": key, "baseline": before, "candidate": after, "allowed": allowed})
    if candidate_primary < baseline_primary:
        status = "rejected"
        reason = "candidate regressed a primary metric"
    elif candidate_primary == baseline_primary and cost_regressions:
        status = "rejected"
        reason = "primary metrics tied while efficiency materially regressed"
    elif not heldout_verified:
        status = "needs_heldout"
        reason = "candidate passed validation comparison but lacks independent heldout evidence"
    else:
        status = "promoted"
        reason = "primary outcome and efficiency gate passed with heldout verification"
    return {
        "status": status,
        "promoted": status == "promoted",
        "reason": reason,
        "baseline_primary": dict(zip(primary, baseline_primary)),
        "candidate_primary": dict(zip(primary, candidate_primary)),
        "cost_regressions": cost_regressions,
        "heldout_verified": bool(heldout_verified),
    }


def paired_flow_promotion_decision(
    validation_pairs: Iterable[Mapping[str, Any]],
    heldout_pairs: Iterable[Mapping[str, Any]],
    *,
    primary_metrics: Iterable[str],
    cost_metrics: Iterable[str] = (),
    min_validation_cases: int = 2,
    min_heldout_cases: int = 2,
    cost_regression_tolerance: float = 0.05,
    min_cost_improvement: float = 0.05,
    max_primary_losses: int = 0,
) -> dict[str, Any]:
    """Gate a Flow using paired validation and held-out empirical results.

    Each item is ``{"case_id": ..., "baseline": {...}, "candidate": {...}}``.
    A boolean cannot stand in for held-out evidence: case IDs must be unique and
    both arms must contain every declared metric.
    """

    primary = list(primary_metrics)
    costs = list(cost_metrics)
    if not primary:
        raise FlowVariantError("paired promotion requires primary metrics")

    def summarize(raw_pairs: Iterable[Mapping[str, Any]], split: str) -> dict[str, Any]:
        pairs = list(raw_pairs)
        seen: set[str] = set()
        details = []
        baseline_sums = {key: 0.0 for key in (*primary, *costs)}
        candidate_sums = {key: 0.0 for key in (*primary, *costs)}
        wins = losses = ties = 0
        for index, pair in enumerate(pairs):
            if not isinstance(pair, Mapping):
                raise FlowVariantError(f"{split} pair {index} is not an object")
            case_id = str(pair.get("case_id", "")).strip()
            if not case_id or case_id in seen:
                raise FlowVariantError(f"{split} has missing or duplicate case_id {case_id!r}")
            seen.add(case_id)
            baseline = pair.get("baseline")
            candidate = pair.get("candidate")
            if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
                raise FlowVariantError(f"{split} case {case_id} requires baseline and candidate")
            for key in (*primary, *costs):
                if key not in baseline or key not in candidate:
                    raise FlowVariantError(f"{split} case {case_id} is missing metric {key!r}")
                try:
                    baseline_sums[key] += float(baseline[key] or 0)
                    candidate_sums[key] += float(candidate[key] or 0)
                except (TypeError, ValueError) as error:
                    raise FlowVariantError(
                        f"{split} case {case_id} metric {key!r} must be numeric"
                    ) from error
            before = tuple(float(baseline[key] or 0) for key in primary)
            after = tuple(float(candidate[key] or 0) for key in primary)
            relation = "win" if after > before else "loss" if after < before else "tie"
            wins += relation == "win"
            losses += relation == "loss"
            ties += relation == "tie"
            details.append({"case_id": case_id, "relation": relation})
        count = len(pairs)
        baseline_means = {key: baseline_sums[key] / count for key in baseline_sums} if count else {}
        candidate_means = {key: candidate_sums[key] / count for key in candidate_sums} if count else {}
        return {
            "split": split,
            "cases": count,
            "wins": int(wins),
            "losses": int(losses),
            "ties": int(ties),
            "baseline_mean": baseline_means,
            "candidate_mean": candidate_means,
            "details": details,
        }

    validation = summarize(validation_pairs, "validation")
    heldout = summarize(heldout_pairs, "heldout")
    reasons: list[str] = []
    status = "promoted"
    if validation["cases"] < max(1, int(min_validation_cases)):
        status = "needs_more_evidence"
        reasons.append("insufficient paired validation cases")
    if heldout["cases"] < max(1, int(min_heldout_cases)):
        status = "needs_more_evidence"
        reasons.append("insufficient paired held-out cases")

    for summary in (validation, heldout):
        if summary["losses"] > max(0, int(max_primary_losses)):
            status = "rejected"
            reasons.append(f"{summary['split']} contains primary-metric regressions")
        if summary["cases"]:
            before = tuple(summary["baseline_mean"][key] for key in primary)
            after = tuple(summary["candidate_mean"][key] for key in primary)
            if after < before:
                status = "rejected"
                reasons.append(f"{summary['split']} aggregate primary metrics regressed")
            if after == before:
                for key in costs:
                    baseline_cost = summary["baseline_mean"][key]
                    candidate_cost = summary["candidate_mean"][key]
                    allowed = baseline_cost * (1 + max(0.0, float(cost_regression_tolerance)))
                    if candidate_cost > allowed:
                        status = "rejected"
                        reasons.append(
                            f"{summary['split']} primary tied while {key} regressed materially"
                        )

    any_primary_win = validation["wins"] + heldout["wins"] > 0
    cost_improved_splits: list[str] = []
    for summary in (validation, heldout):
        if not summary["cases"]:
            continue
        improved = any(
            summary["baseline_mean"][key] > 0
            and summary["candidate_mean"][key]
            <= summary["baseline_mean"][key] * (1 - max(0.0, float(min_cost_improvement)))
            for key in costs
        )
        if improved:
            cost_improved_splits.append(summary["split"])
    reproducible_cost_gain = all(
        split in cost_improved_splits for split in ("validation", "heldout")
    )
    if status == "promoted" and not any_primary_win and not reproducible_cost_gain:
        status = "rejected"
        reasons.append(
            "candidate produced no primary gain and no reproducible material efficiency improvement"
        )
    return {
        "status": status,
        "promoted": status == "promoted",
        "reason": "; ".join(dict.fromkeys(reasons)) or "paired validation and held-out gates passed",
        "validation": validation,
        "heldout": heldout,
        "requirements": {
            "min_validation_cases": int(min_validation_cases),
            "min_heldout_cases": int(min_heldout_cases),
            "max_primary_losses": int(max_primary_losses),
            "cost_regression_tolerance": float(cost_regression_tolerance),
            "min_cost_improvement": float(min_cost_improvement),
        },
        "cost_improved_splits": cost_improved_splits,
    }


__all__ = [
    "FlowVariantError", "apply_flow_variant", "build_flow_variant_population", "flow_digest",
    "flow_promotion_decision", "paired_flow_promotion_decision", "proposal_signature",
    "validate_proposal_evidence", "write_flow_variant",
]
