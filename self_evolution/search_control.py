"""Typed belief and experiment control for long-horizon search Flows.

The model proposes hypotheses and experiments; this module owns the state
boundary.  It prevents silent loss of falsified beliefs, unsupported confidence
jumps and repeated low-information actions.  Nothing here knows ARC, code, or
any other task domain.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Iterable, Mapping


class SearchControlError(ValueError):
    """A proposed scientific-search update violates the typed contract."""


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_STATUSES = {"candidate", "supported", "falsified", "uncertain"}
_EVIDENCE_KINDS = {"observation", "support", "counterexample"}


def action_signature(action: Mapping[str, Any] | None) -> str:
    """Canonicalize an action while excluding prose annotations."""

    if not isinstance(action, Mapping):
        return ""
    payload = {
        str(key): value
        for key, value in action.items()
        if str(key) not in {"prediction", "reasoning", "rationale"}
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def recent_action_signatures(trajectory: Any, *, limit: int = 12) -> list[str]:
    """Extract successful environment/tool actions from an EgoAgent trajectory."""

    if not isinstance(trajectory, list):
        return []
    signatures: list[str] = []
    for item in trajectory:
        if not isinstance(item, Mapping) or item.get("ok") is False:
            continue
        arguments = item.get("arguments")
        if not isinstance(arguments, Mapping):
            continue
        action: dict[str, Any] = {}
        if isinstance(arguments.get("action"), Mapping):
            action.update(arguments["action"])
        elif arguments.get("action"):
            action["name"] = arguments.get("action")
        elif item.get("action"):
            action["name"] = item.get("action")
        for key in ("x", "y", "index", "target", "query"):
            if key in arguments:
                action[key] = arguments[key]
        signature = action_signature(action)
        if signature:
            signatures.append(signature)
    return signatures[-max(0, int(limit)):]


def latest_available_actions(trajectory: Any) -> list[str]:
    """Read the latest advertised action set from a tool observation."""

    if not isinstance(trajectory, list):
        return []
    for item in reversed(trajectory):
        if not isinstance(item, Mapping):
            continue
        observation = item.get("observation")
        if isinstance(observation, str):
            try:
                observation = json.loads(observation)
            except ValueError:
                continue
        if not isinstance(observation, Mapping):
            continue
        actions = observation.get("available_actions")
        if isinstance(actions, list):
            return [str(action) for action in actions if str(action).strip()]
    return []


def _evidence(raw: Any, hypothesis_id: str, errors: list[str]) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"hypothesis {hypothesis_id}: evidence must be a list")
        return []
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw[:32]):
        if not isinstance(item, Mapping):
            errors.append(f"hypothesis {hypothesis_id}: evidence {index} must be an object")
            continue
        kind = str(item.get("kind", "observation")).lower()
        ref = str(item.get("ref", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if kind not in _EVIDENCE_KINDS or not ref or not summary:
            errors.append(
                f"hypothesis {hypothesis_id}: evidence {index} requires kind, ref and summary"
            )
            continue
        marker = (kind, ref)
        if marker in seen:
            continue
        seen.add(marker)
        result.append({"kind": kind, "ref": ref[:160], "summary": summary[:800]})
    return result


def reconcile_search_state(
    current: Mapping[str, Any] | None,
    proposal: Mapping[str, Any],
    *,
    allowed_actions: Iterable[str] | None = None,
    recent_actions: Iterable[str] = (),
    max_hypotheses: int = 8,
    max_experiments: int = 12,
    coordinate_min: int | None = None,
    coordinate_max: int | None = None,
) -> dict[str, Any]:
    """Reconcile one model proposal and deterministically select an experiment."""

    if not isinstance(proposal, Mapping):
        raise SearchControlError("search proposal must be an object")
    state = copy.deepcopy(dict(current or {}))
    old_hypotheses = {
        str(item.get("id")): copy.deepcopy(item)
        for item in state.get("hypotheses", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    errors: list[str] = []
    audit: list[dict[str, Any]] = []
    proposed_hypotheses = proposal.get("hypotheses", [])
    if not isinstance(proposed_hypotheses, list):
        proposed_hypotheses = []
        errors.append("hypotheses must be a list")

    merged: dict[str, dict[str, Any]] = copy.deepcopy(old_hypotheses)
    seen_hypotheses: set[str] = set()
    for index, raw in enumerate(proposed_hypotheses[:max(1, int(max_hypotheses))]):
        if not isinstance(raw, Mapping):
            errors.append(f"hypothesis {index} must be an object")
            continue
        hypothesis_id = str(raw.get("id", "")).strip()
        if not _ID.fullmatch(hypothesis_id) or hypothesis_id in seen_hypotheses:
            errors.append(f"invalid or duplicate hypothesis id: {hypothesis_id!r}")
            continue
        seen_hypotheses.add(hypothesis_id)
        claim = str(raw.get("claim", "")).strip()
        status = str(raw.get("status", "candidate")).lower()
        confidence = raw.get("confidence", 0.5)
        if not claim or status not in _STATUSES:
            errors.append(f"hypothesis {hypothesis_id}: invalid claim or status")
            continue
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"hypothesis {hypothesis_id}: confidence must be in [0, 1]")
            continue
        evidence = _evidence(raw.get("evidence"), hypothesis_id, errors)
        previous = old_hypotheses.get(hypothesis_id, {})
        previous_evidence = {
            (str(item.get("kind")), str(item.get("ref")))
            for item in previous.get("evidence", [])
            if isinstance(item, Mapping)
        }
        new_support_refs = {
            item["ref"]
            for item in evidence
            if item["kind"] == "support" and (item["kind"], item["ref"]) not in previous_evidence
        }
        new_support = bool(new_support_refs)
        if previous.get("status") == "falsified" and status != "falsified" and not new_support:
            status = "falsified"
            confidence = min(float(confidence), float(previous.get("confidence", 0.1) or 0.1))
            audit.append({"type": "blocked_reactivation", "hypothesis_id": hypothesis_id})
        previous_confidence = float(previous.get("confidence", 0) or 0)
        maximum_increase = 0.2 * max(1, len(new_support_refs))
        if float(confidence) > previous_confidence + maximum_increase and previous:
            confidence = previous_confidence + maximum_increase
            audit.append({"type": "bounded_confidence_increase", "hypothesis_id": hypothesis_id})
        if status == "falsified" and not any(item["kind"] == "counterexample" for item in evidence):
            errors.append(f"hypothesis {hypothesis_id}: falsified status requires counterexample evidence")
            status = "uncertain"
        merged[hypothesis_id] = {
            "id": hypothesis_id,
            "claim": claim[:1200],
            "status": status,
            "confidence": round(float(confidence), 4),
            "evidence": evidence,
        }

    # A model may omit an old hypothesis to save context, but omission must
    # never erase a durable falsification/counterexample.
    hypotheses = list(merged.values())
    hypotheses.sort(
        key=lambda item: (
            item.get("status") == "falsified",
            -float(item.get("confidence", 0)),
            str(item.get("id")),
        )
    )
    hypotheses = hypotheses[:max(1, int(max_hypotheses))]
    known_ids = {str(item["id"]) for item in hypotheses}
    active_ids = {str(item["id"]) for item in hypotheses if item.get("status") != "falsified"}

    allowed = {str(item).upper() for item in (allowed_actions or []) if str(item).strip()}
    recent = list(recent_actions)
    recent_counts = {signature: recent.count(signature) for signature in set(recent)}
    raw_experiments = proposal.get("experiments", [])
    if not isinstance(raw_experiments, list):
        raw_experiments = []
        errors.append("experiments must be a list")
    experiments: list[dict[str, Any]] = []
    seen_experiments: set[str] = set()
    for index, raw in enumerate(raw_experiments[:max(1, int(max_experiments))]):
        if not isinstance(raw, Mapping):
            errors.append(f"experiment {index} must be an object")
            continue
        experiment_id = str(raw.get("id", "")).strip()
        action = raw.get("action")
        if not _ID.fullmatch(experiment_id) or experiment_id in seen_experiments:
            errors.append(f"invalid or duplicate experiment id: {experiment_id!r}")
            continue
        if not isinstance(action, Mapping) or not str(action.get("name", "")).strip():
            errors.append(f"experiment {experiment_id}: action requires a name")
            continue
        action = copy.deepcopy(dict(action))
        action["name"] = str(action["name"]).upper()
        if allowed and action["name"] not in allowed:
            errors.append(f"experiment {experiment_id}: action {action['name']} is not currently available")
            continue
        has_x, has_y = "x" in action, "y" in action
        if has_x != has_y:
            errors.append(f"experiment {experiment_id}: x and y must be supplied together")
            continue
        if has_x:
            if any(isinstance(action[key], bool) or not isinstance(action[key], int) for key in ("x", "y")):
                errors.append(f"experiment {experiment_id}: x and y must be integers")
                continue
            if coordinate_min is not None and min(action["x"], action["y"]) < coordinate_min:
                errors.append(f"experiment {experiment_id}: coordinates are below {coordinate_min}")
                continue
            if coordinate_max is not None and max(action["x"], action["y"]) > coordinate_max:
                errors.append(f"experiment {experiment_id}: coordinates exceed {coordinate_max}")
                continue
        discriminates = [
            str(item) for item in raw.get("discriminates", [])
            if str(item) in known_ids
        ]
        outcomes = [str(item)[:500] for item in raw.get("predicted_outcomes", []) if str(item).strip()][:8]
        scores: dict[str, float] = {}
        score_invalid = False
        for field, default in (
            ("information_gain", 0.0), ("novelty", 0.0),
            ("cost", 0.5), ("repeat_risk", 0.0),
        ):
            value = raw.get(field, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                errors.append(f"experiment {experiment_id}: {field} must be in [0, 1]")
                score_invalid = True
                break
            scores[field] = float(value)
        if score_invalid:
            continue
        signature = action_signature(action)
        repeats = recent_counts.get(signature, 0)
        coverage = len(set(discriminates) & active_ids) / max(1, len(active_ids))
        outcome_quality = min(1.0, len(outcomes) / 2.0)
        selection_score = (
            2.2 * scores["information_gain"]
            + 1.2 * scores["novelty"]
            + 0.8 * coverage
            + 0.4 * outcome_quality
            - 0.35 * scores["cost"]
            - 1.4 * scores["repeat_risk"]
            - 1.5 * repeats
        )
        seen_experiments.add(experiment_id)
        experiments.append({
            "id": experiment_id,
            "action": action,
            "discriminates": discriminates,
            "predicted_outcomes": outcomes,
            **scores,
            "rationale": str(raw.get("rationale", ""))[:1000],
            "action_signature": signature,
            "recent_repeats": repeats,
            "selection_score": round(selection_score, 6),
        })
    experiments.sort(key=lambda item: (-item["selection_score"], item["id"]))
    selected = copy.deepcopy(experiments[0]) if experiments else None
    revision = int(state.get("revision", 0) or 0) + 1
    ledger = {
        "version": 1,
        "revision": revision,
        "hypotheses": hypotheses,
        "experiments": experiments,
        "selected_experiment_id": selected.get("id") if selected else None,
        "update_reason": str(proposal.get("update_reason", ""))[:1000],
    }
    return {
        "ok": bool(selected),
        "ledger": ledger,
        "selected": selected,
        "errors": errors,
        "audit": audit,
        "recent_action_count": len(recent),
    }


__all__ = [
    "SearchControlError", "action_signature", "latest_available_actions", "recent_action_signatures",
    "reconcile_search_state",
]
