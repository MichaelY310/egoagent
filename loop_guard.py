"""Deterministic, model-visible guards for repeated tool-call loops.

Policy lives in a Flow node. This module validates that policy, advances one
per-session chain and produces source-attributed reminders. It never blocks,
rewrites or executes a tool call.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
from typing import Any, Iterable, Mapping


GENTLE_REMINDER = (
    "You are repeating the exact same tool call with identical arguments. "
    "Carefully analyze the previous result before calling again: if the task is "
    "not complete, try a different approach or different arguments instead of "
    "repeating the call."
)


class LoopGuardError(ValueError):
    """The declared loop-guard policy is invalid."""


def validate_thresholds(values: Iterable[Any]) -> list[int]:
    thresholds = list(values)
    if not thresholds:
        raise LoopGuardError("loop guard thresholds must not be empty")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in thresholds):
        raise LoopGuardError("every loop guard threshold must be an integer >= 2")
    if len(set(thresholds)) != len(thresholds):
        raise LoopGuardError("loop guard thresholds must not contain duplicates")
    return sorted(thresholds)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _tracked(name: str, include: list[str], exclude: list[str]) -> bool:
    if include and not any(fnmatch.fnmatchcase(name, pattern) for pattern in include):
        return False
    return not any(fnmatch.fnmatchcase(name, pattern) for pattern in exclude)


def _preview(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return f"{value[:maximum]}… (+{len(value) - maximum} more chars)"


def observe_tool_trajectory(
    state: Mapping[str, Any] | None,
    trajectory: Any,
    *,
    thresholds: Iterable[int] = (3, 5, 8),
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
    arguments_preview_chars: int = 500,
) -> dict[str, Any]:
    """Advance a repeat chain from newly appended trajectory entries.

    ``processed_length`` makes repeated component execution idempotent. Calls
    filtered by ``include``/``exclude`` are transparent: they neither count nor
    reset the tracked chain, matching DeepSeek Harness's guard semantics.
    """

    configured = validate_thresholds(thresholds)
    if isinstance(arguments_preview_chars, bool) or not isinstance(arguments_preview_chars, int) or arguments_preview_chars < 1:
        raise LoopGuardError("arguments_preview_chars must be an integer >= 1")
    include_patterns = [str(value) for value in include if str(value)]
    exclude_patterns = [str(value) for value in exclude if str(value)]
    items = trajectory if isinstance(trajectory, list) else []
    next_state = copy.deepcopy(dict(state or {}))
    processed = max(0, int(next_state.get("processed_length", 0) or 0))
    if processed > len(items):
        next_state = {}
        processed = 0

    reminders: list[dict[str, Any]] = []
    observed = 0
    for item in items[processed:]:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("action") or item.get("tool") or "").strip()
        arguments = item.get("arguments", {})
        if not name or not _tracked(name, include_patterns, exclude_patterns):
            continue
        observed += 1
        canonical_arguments = _canonical(arguments)
        signature = hashlib.sha256(_canonical([name, canonical_arguments]).encode("utf-8")).hexdigest()
        count = int(next_state.get("count", 0) or 0) + 1 if signature == next_state.get("signature_sha256") else 1
        next_state.update({"signature_sha256": signature, "tool": name, "count": count})
        if count not in configured:
            continue
        if count == configured[0]:
            text = GENTLE_REMINDER
        else:
            text = (
                "Repeated tool call detected:\n"
                f"- tool: {name}\n"
                f"- consecutive_calls: {count}\n"
                f"- arguments: {_preview(canonical_arguments, arguments_preview_chars)}\n"
                "The repeated calls are not making progress. Do not call this tool with "
                "these exact arguments again. Inspect the latest result and choose a "
                "different action, different arguments, or finish the task if enough "
                "evidence has been gathered."
            )
        reminders.append({"tool": name, "count": count, "text": text, "signature_sha256": signature})

    next_state["processed_length"] = len(items)
    return {
        "state": next_state,
        "reminders": reminders,
        "reminded": bool(reminders),
        "observed": observed,
        "thresholds": configured,
    }


def reset_loop_guard(trajectory: Any = None) -> dict[str, Any]:
    items = trajectory if isinstance(trajectory, list) else []
    return {"processed_length": len(items), "signature_sha256": None, "tool": None, "count": 0}


__all__ = [
    "GENTLE_REMINDER", "LoopGuardError", "observe_tool_trajectory",
    "reset_loop_guard", "validate_thresholds",
]
