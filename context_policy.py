"""Auditable context curation for long-running EgoAgent sessions.

The full transcript is immutable from the model-context point of view: every
message stays available to the UI and can be restored.  This module derives a
smaller working view and records why each source message was kept, compressed,
summarized, or elided.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


TOOL_RESPONSE_RE = re.compile(r"<tool_response>(.*?)</tool_response>", re.DOTALL)
TOOL_PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"
PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+|(?:\.{0,2}[\\/])?[\w.-]+(?:[\\/][\w .@+()-]+)+\.[A-Za-z0-9]{1,12})"
)
ERROR_LINE_RE = re.compile(r"\b(error|exception|failed|failure|denied|timeout|traceback|exit code|errno)\b", re.I)
PORT_RE = re.compile(r"(?:\bport|端口)\s*[:=#]?\s*\d{2,5}\b", re.I)
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9_-]{1,15}\b")
BACKTICK_RE = re.compile(r"`([^`\n]{1,120})`")


def estimate_tokens(value: Any) -> int:
    if isinstance(value, list):
        return sum(estimate_tokens(item) + 4 for item in value)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return max(1, (len(str(value)) + 3) // 4)


def content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content)


def is_tool_observation(message: dict[str, Any]) -> bool:
    content = content_text(message)
    return message.get("role") == "tool" or "<tool_response>" in content or message.get("message_type") == "observation"


def is_conversation_user(message: dict[str, Any]) -> bool:
    return message.get("role") == "user" and not is_tool_observation(message) and message.get("name") != "tool_image"


def ensure_message_ids(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, original in enumerate(messages):
        message = copy.deepcopy(original)
        if not message.get("_message_id"):
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "role": message.get("role"),
                        "name": message.get("name"),
                        "content": message.get("content"),
                        "tool_calls": message.get("tool_calls"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:16]
            occurrence = seen.get(fingerprint, 0)
            seen[fingerprint] = occurrence + 1
            message["_message_id"] = f"msg_{fingerprint}_{occurrence}_{index}"
        result.append(message)
    return result


@dataclass(frozen=True)
class ConversationTurn:
    id: str
    message_ids: tuple[str, ...]
    messages: tuple[dict[str, Any], ...]

    def preview(self, max_chars: int = 1400) -> dict[str, Any]:
        snippets = []
        for message in self.messages:
            text = content_text(message).strip()
            if not text:
                continue
            snippets.append(
                {
                    "message_id": message.get("_message_id"),
                    "role": message.get("role"),
                    "name": message.get("name"),
                    "tool_observation": is_tool_observation(message),
                    "text": text[:500],
                }
            )
        serialized = json.dumps(snippets, ensure_ascii=False)
        if len(serialized) > max_chars:
            serialized = serialized[:max_chars] + "…"
        return {"turn_id": self.id, "messages": snippets, "preview": serialized}


@dataclass(frozen=True)
class ContextBlock:
    """Protocol-safe unit presented to the pressure compactor."""

    id: str
    kind: str
    message_ids: tuple[str, ...]
    messages: tuple[dict[str, Any], ...]
    protected: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(list(self.messages))

    def preview(self, max_chars: int = 2400) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        remaining = max(300, int(max_chars))
        for message in self.messages:
            text = content_text(message).strip()
            reasoning = str(message.get("reasoning_content") or "").strip()
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            rendered = {
                "role": message.get("role"),
                "name": message.get("name"),
                "text": text[: min(1200, remaining)],
                "reasoning": reasoning[: min(900, remaining)] if reasoning else "",
                "tools": [
                    {
                        "name": call.get("function", {}).get("name", ""),
                        "arguments": str(call.get("function", {}).get("arguments", ""))[:500],
                    }
                    for call in tool_calls[:8] if isinstance(call, dict)
                ],
            }
            parts.append(rendered)
            remaining -= len(json.dumps(rendered, ensure_ascii=False, default=str))
            if remaining <= 0:
                break
        return {
            "block_id": self.id,
            "kind": self.kind,
            "tokens_estimated": self.tokens,
            "protected": self.protected,
            "message_ids": list(self.message_ids),
            "content": parts,
            "anchors": extract_anchors(self.messages, limit=12),
        }


def conversation_turns(messages: Iterable[dict[str, Any]]) -> list[ConversationTurn]:
    normalized = ensure_message_ids(messages)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in normalized:
        if is_conversation_user(message) and current:
            groups.append(current)
            current = []
        # System messages before the first user remain their own protected
        # prefix rather than being considered a removable conversation turn.
        if message.get("role") == "system" and not groups and not current:
            groups.append([message])
            continue
        current.append(message)
    if current:
        groups.append(current)
    turns = []
    for group in groups:
        ids = tuple(str(message["_message_id"]) for message in group)
        digest = hashlib.sha256("\0".join(ids).encode("utf-8")).hexdigest()[:16]
        turns.append(ConversationTurn(f"turn_{digest}", ids, tuple(group)))
    return turns


def context_blocks(
    messages: Iterable[dict[str, Any]],
    *,
    protect_recent_turns: int = 2,
) -> list[ContextBlock]:
    """Partition history without separating a tool call from its result."""

    normalized = ensure_message_ids(messages)
    turns = conversation_turns(normalized)
    recent_ids = {
        message_id
        for turn in turns[-max(1, int(protect_recent_turns)):]
        for message_id in turn.message_ids
    }
    blocks: list[ContextBlock] = []
    index = 0
    while index < len(normalized):
        message = normalized[index]
        group = [message]
        role = str(message.get("role") or "")
        content = content_text(message)
        if role == "system":
            kind = "system"
        elif role == "assistant" and (message.get("tool_calls") or "<tool_call>" in content):
            kind = "tool_exchange"
            cursor = index + 1
            while cursor < len(normalized) and is_tool_observation(normalized[cursor]):
                group.append(normalized[cursor])
                cursor += 1
            index = cursor - 1
        elif is_tool_observation(message):
            kind = "tool_result"
        elif is_conversation_user(message):
            kind = "user_requirement"
        elif role == "assistant" and message.get("reasoning_content"):
            kind = "assistant_reasoning"
        elif message.get("conversation_summary"):
            kind = "prior_summary"
        elif role == "assistant":
            kind = "assistant_answer"
        else:
            kind = "runtime_message"
        ids = tuple(str(item["_message_id"]) for item in group)
        digest = hashlib.sha256((kind + "\0" + "\0".join(ids)).encode("utf-8")).hexdigest()[:16]
        protected = kind == "system" or any(message_id in recent_ids for message_id in ids)
        blocks.append(ContextBlock(f"block_{digest}", kind, ids, tuple(group), protected))
        index += 1
    return blocks


def review_batch(
    messages: Iterable[dict[str, Any]],
    reviewed_turn_ids: Iterable[str] = (),
    *,
    interval: int = 5,
    protect_recent: int = 2,
) -> list[ConversationTurn]:
    turns = conversation_turns(messages)
    reviewed = set(reviewed_turn_ids)
    candidates = [
        turn
        for turn in turns[:-max(1, protect_recent)]
        if turn.id not in reviewed and not all(message.get("role") == "system" for message in turn.messages)
    ]
    interval = max(1, int(interval))
    return candidates[:interval] if len(candidates) >= interval else []


def _tool_payload(message: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    content = content_text(message)
    match = TOOL_RESPONSE_RE.search(content)
    if not match:
        return None, content
    try:
        payload = json.loads(match.group(1))
        if not isinstance(payload, dict):
            return None, content
        return payload, str(payload.get("content", ""))
    except (TypeError, json.JSONDecodeError):
        return None, content


def compress_tool_observation(message: dict[str, Any], max_chars: int = 1800) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Compress a tool result while preserving its protocol envelope."""
    copied = copy.deepcopy(message)
    payload, observation = _tool_payload(copied)
    if len(observation) <= max(200, int(max_chars)):
        return copied, None
    lines = observation.splitlines()
    important = []
    for line in lines:
        if ERROR_LINE_RE.search(line) or PATH_RE.search(line):
            value = line.strip()
            if value and value not in important:
                important.append(value[:500])
        if len(important) >= 12:
            break
    head = lines[:8]
    tail = lines[-8:] if len(lines) > 8 else []
    kept = []
    for line in [*head, *important, *tail]:
        if line not in kept:
            kept.append(line)
    replacement = "\n".join(kept)
    if len(replacement) > max_chars:
        replacement = replacement[:max_chars]
    replacement += (
        f"\n[… context curator compressed {len(observation) - len(replacement)} characters "
        f"from {len(lines)} lines; original remains in full transcript]"
    )
    if payload is not None:
        payload["content"] = replacement
        copied["content"] = f"<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>"
    else:
        copied["content"] = replacement
    annotation = {
        "status": "compressed",
        "reason": "large_tool_observation",
        "original_chars": len(observation),
        "working_chars": len(replacement),
        "replacement": replacement,
    }
    copied["_context"] = annotation
    return copied, annotation


def prune_tool_observation(
    message: dict[str, Any],
    *,
    threshold_chars: int = 8192,
    head_chars: int = 4096,
    tail_chars: int = 1024,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Replace an oversized tool result's middle without touching its audit copy."""

    for name, value, positive in (
        ("threshold_chars", threshold_chars, True),
        ("head_chars", head_chars, False),
        ("tail_chars", tail_chars, False),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
            qualifier = "positive" if positive else "non-negative"
            raise ValueError(f"{name} must be a {qualifier} integer")
    if head_chars + len(TOOL_PRUNE_MARKER) + tail_chars > threshold_chars:
        raise ValueError("head_chars + marker + tail_chars must not exceed threshold_chars")
    copied = copy.deepcopy(message)
    payload, observation = _tool_payload(copied)
    if len(observation) <= threshold_chars:
        return copied, None
    tail = observation[-tail_chars:] if tail_chars else ""
    replacement = observation[:head_chars] + TOOL_PRUNE_MARKER + tail
    if payload is not None:
        payload["content"] = replacement
        copied["content"] = f"<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>"
    else:
        copied["content"] = replacement
    annotation = {
        "status": "pruned",
        "reason": "oversized_tool_result",
        "original_chars": len(observation),
        "working_chars": len(replacement),
        "removed_chars": len(observation) - len(replacement),
    }
    copied["_context"] = annotation
    return copied, annotation


def apply_tool_result_pruning(
    working_messages: Iterable[dict[str, Any]],
    full_messages: Iterable[dict[str, Any]],
    *,
    threshold_chars: int = 8192,
    head_chars: int = 4096,
    tail_chars: int = 1024,
    previous_ledger: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Prune the current model surface while retaining the complete transcript."""

    working = ensure_message_ids(working_messages)
    full = ensure_message_ids(full_messages)
    output: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    removed = 0
    for message in working:
        if not is_tool_observation(message):
            output.append(copy.deepcopy(message))
            continue
        pruned, annotation = prune_tool_observation(
            message,
            threshold_chars=threshold_chars,
            head_chars=head_chars,
            tail_chars=tail_chars,
        )
        output.append(pruned)
        if annotation:
            removed += int(annotation["removed_chars"])
            entries.append({"action": "prune_tool_result", "message_id": message.get("_message_id"), **annotation})
    before_tokens = estimate_tokens(working)
    after_tokens = estimate_tokens(output)
    return {
        "messages": output,
        "full_messages": full,
        "ledger": [copy.deepcopy(item) for item in previous_ledger if isinstance(item, dict)] + entries,
        "stats": {
            "pruned_tool_results": len(entries),
            "removed_chars": removed,
            "before_tokens_estimated": before_tokens,
            "after_tokens_estimated": after_tokens,
            "saved_tokens_estimated": max(0, before_tokens - after_tokens),
        },
    }


def extract_anchors(messages: Iterable[dict[str, Any]], limit: int = 24) -> list[str]:
    anchors: list[str] = []
    for message in messages:
        text = content_text(message)
        reasoning = str(message.get("reasoning_content") or "")
        evidence = "\n".join(value for value in (text, reasoning) if value)
        for match in PATH_RE.findall(evidence):
            cleaned = match.rstrip(".,:;)")
            if cleaned not in anchors:
                anchors.append(cleaned)
        for match in PORT_RE.findall(evidence):
            cleaned = match.strip()
            if cleaned not in anchors:
                anchors.append(cleaned)
        for match in BACKTICK_RE.findall(evidence):
            cleaned = f"`{match.strip()}`"
            if cleaned not in anchors:
                anchors.append(cleaned)
        for match in ACRONYM_RE.findall(evidence):
            # Common one-word protocol/algorithm names are cheap to retain and
            # difficult to reconstruct once a model paraphrases them away.
            if match not in anchors:
                anchors.append(match)
        for call in message.get("tool_calls", []) if isinstance(message.get("tool_calls"), list) else []:
            if not isinstance(call, dict):
                continue
            function = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
            arguments = str(function.get("arguments") or "").strip()
            tool_anchor = f"tool {name}({arguments[:300]})" if name else ""
            if tool_anchor and tool_anchor not in anchors:
                anchors.append(tool_anchor)
        for line in evidence.splitlines():
            if ERROR_LINE_RE.search(line):
                cleaned = line.strip()[:240]
                if cleaned and cleaned not in anchors:
                    anchors.append(cleaned)
        if len(anchors) >= limit:
            break
    return anchors[:limit]


def _faithful_summary(summary: str, messages: Iterable[dict[str, Any]]) -> str:
    anchors = extract_anchors(messages)
    missing = [anchor for anchor in anchors if anchor not in summary]
    if not missing:
        return summary.strip()
    appendix = "\n\nPreserved exact anchors:\n" + "\n".join(f"- {anchor}" for anchor in missing)
    return summary.strip() + appendix


def apply_context_decisions(
    full_messages: Iterable[dict[str, Any]],
    decisions: Iterable[dict[str, Any]] = (),
    *,
    protect_recent: int = 2,
    max_tool_chars: int = 1800,
) -> dict[str, Any]:
    """Return annotated audit messages and a compact working transcript."""
    audit = ensure_message_ids(full_messages)
    turns = conversation_turns(audit)
    decision_map = {
        str(item.get("turn_id")): item
        for item in decisions
        if isinstance(item, dict) and item.get("turn_id")
    }
    protected_ids = {
        message_id
        for turn in turns[-max(1, int(protect_recent)):]
        for message_id in turn.message_ids
    }
    by_id = {str(message["_message_id"]): message for message in audit}
    working: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    elided = summarized = compressed = 0

    for turn in turns:
        decision = decision_map.get(turn.id, {})
        action = str(decision.get("action", "keep")).lower()
        if any(message_id in protected_ids for message_id in turn.message_ids):
            action = "keep"
        if all(message.get("role") == "system" for message in turn.messages):
            action = "keep"
        if action not in {"keep", "summarize", "elide"}:
            action = "keep"
        reason = str(decision.get("reason") or "retained_by_default")

        if action == "elide":
            for message_id in turn.message_ids:
                by_id[message_id]["_context"] = {
                    "status": "elided",
                    "reason": reason,
                    "turn_id": turn.id,
                    "model_visible": False,
                }
            elided += len(turn.message_ids)
            ledger.append({"turn_id": turn.id, "action": action, "reason": reason, "source_message_ids": list(turn.message_ids)})
            continue

        if action == "summarize":
            raw_summary = str(decision.get("summary") or "").strip()
            if not raw_summary:
                # A missing summary is not safe grounds for information loss.
                action = "keep"
                reason = "summary_missing_fallback_keep"
            else:
                summary = _faithful_summary(raw_summary, turn.messages)
                summary_message = {
                    "role": "system",
                    "name": "context_curator",
                    "content": summary,
                    "conversation_summary": True,
                    "_context": {
                        "status": "summary",
                        "reason": reason,
                        "turn_id": turn.id,
                        "source_message_ids": list(turn.message_ids),
                    },
                }
                working.append(summary_message)
                for message_id in turn.message_ids:
                    by_id[message_id]["_context"] = {
                        "status": "summarized",
                        "reason": reason,
                        "turn_id": turn.id,
                        "model_visible": False,
                        "replacement": summary,
                    }
                summarized += len(turn.message_ids)
                ledger.append({"turn_id": turn.id, "action": action, "reason": reason, "source_message_ids": list(turn.message_ids), "summary": summary})
                continue

        for source in turn.messages:
            message_id = str(source["_message_id"])
            current = copy.deepcopy(by_id[message_id])
            if is_tool_observation(current) and int(max_tool_chars) > 0:
                current, annotation = compress_tool_observation(current, max_chars=max_tool_chars)
                if annotation:
                    by_id[message_id]["_context"] = {**annotation, "model_visible": True, "turn_id": turn.id}
                    compressed += 1
            else:
                by_id[message_id]["_context"] = {
                    "status": "active",
                    "reason": reason,
                    "turn_id": turn.id,
                    "model_visible": True,
                }
            working.append(current)
        ledger.append({"turn_id": turn.id, "action": "keep", "reason": reason, "source_message_ids": list(turn.message_ids)})

    before_tokens = estimate_tokens(audit)
    after_tokens = estimate_tokens(working)
    return {
        "full_messages": audit,
        "messages": working,
        "ledger": ledger,
        "stats": {
            "before_tokens_estimated": before_tokens,
            "after_tokens_estimated": after_tokens,
            "saved_tokens_estimated": max(0, before_tokens - after_tokens),
            "reduction_ratio": round(max(0, before_tokens - after_tokens) / max(1, before_tokens), 4),
            "elided_messages": elided,
            "summarized_messages": summarized,
            "compressed_observations": compressed,
        },
    }


def restore_full_context(full_messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    restored = ensure_message_ids(full_messages)
    for message in restored:
        message.pop("_context", None)
    return restored


def pressure_budget(
    messages: Iterable[dict[str, Any]],
    *,
    context_limit_tokens: int,
    high_watermark: float = 0.82,
    target_ratio: float = 0.62,
    reserved_output_tokens: int = 4096,
    extra_input_tokens: int = 0,
) -> dict[str, Any]:
    """Compute a runtime-owned trigger; the Agent never chooses this step."""

    limit = max(1024, int(context_limit_tokens))
    # A misconfigured output cap equal to the whole window would otherwise
    # make every tiny prompt appear over threshold. Keep a usable input region;
    # providers still enforce their real maximum output independently.
    output = min(max(0, int(reserved_output_tokens)), max(256, int(limit * 0.4)))
    high = min(0.98, max(0.2, float(high_watermark)))
    target = min(high - 0.05, max(0.1, float(target_ratio)))
    hard_input_limit = max(1, limit - output)
    threshold = min(int(limit * high), hard_input_limit)
    target_tokens = min(int(limit * target), max(1, threshold - max(256, int(limit * 0.05))))
    message_tokens = estimate_tokens(list(messages))
    rendered_tokens = message_tokens + max(0, int(extra_input_tokens))
    return {
        "triggered": rendered_tokens >= threshold,
        "message_tokens_estimated": message_tokens,
        "rendered_tokens_estimated": rendered_tokens,
        "context_limit_tokens": limit,
        "reserved_output_tokens": output,
        "threshold_tokens": threshold,
        "target_tokens": target_tokens,
        "high_watermark": high,
        "target_ratio": target,
    }


def pressure_compaction_prompt(
    messages: Iterable[dict[str, Any]],
    *,
    current_tokens: int,
    target_tokens: int,
    current_task: str = "",
    protect_recent_turns: int = 2,
) -> tuple[str, list[ContextBlock]]:
    blocks = context_blocks(messages, protect_recent_turns=protect_recent_turns)
    previews = [block.preview() for block in blocks]
    prompt = (
        "You are EgoAgent's context compactor. The RUNTIME has already detected token pressure; "
        "you do not decide whether compaction happens. Author a conservative plan that reduces the working "
        f"history from about {int(current_tokens)} tokens toward {int(target_tokens)} tokens. The complete original "
        "transcript remains available for audit and restoration.\n\n"
        "The runtime partitioned history into protocol-safe blocks:\n"
        "- system: immutable instructions; always keep.\n"
        "- user_requirement: user goals, decisions and constraints; keep or faithfully summarize, never elide.\n"
        "- assistant_reasoning: exploration and hidden reasoning. Remove boilerplate, repeated analysis and dead ends. "
        "Reasoning before a decisive pivot/aha moment may become one sentence, but preserve the post-pivot insight, "
        "evidence and remaining uncertainty.\n"
        "- tool_exchange/tool_result: preserve tool names, state-changing arguments, exact paths, errors, outputs that "
        "support decisions and final outcomes. Collapse raw dumps, repeated searches and resolved failed attempts.\n"
        "- assistant_answer: preserve commitments, results and unfinished work; shorten repetition.\n"
        "- prior_summary/runtime_message: merge duplicates and retain only continuation-relevant state.\n\n"
        "Actions per block: keep, summarize, elide, simplify_reasoning. `elide` is allowed only for redundant assistant "
        "analysis/answers, obsolete runtime noise, or resolved tool traces. `simplify_reasoning` keeps the visible message "
        "but replaces hidden reasoning with the supplied one-sentence summary. Protected blocks should normally be kept.\n\n"
        "Every summary must preserve exact file paths, commands that changed state, error signatures, user decisions, "
        "artifacts, test outcomes and unfinished next steps. Also write `continuation_summary`: a standalone faithful state "
        "summary the runtime may use only if block-level choices do not reach the target.\n\n"
        f"Current task:\n{current_task[:4000]}\n\n"
        f"Blocks:\n{json.dumps(previews, ensure_ascii=False)}\n\n"
        "Return ONLY JSON: {\"blocks\":[{\"block_id\":\"...\",\"action\":\"keep|summarize|elide|simplify_reasoning\"," 
        "\"reason\":\"short reason\",\"summary\":\"required unless keep/elide\"}],"
        "\"continuation_summary\":\"faithful standalone continuation state\"}"
    )
    return prompt, blocks


def apply_pressure_compaction(
    working_messages: Iterable[dict[str, Any]],
    plan: dict[str, Any],
    *,
    target_tokens: int,
    protect_recent_turns: int = 2,
    full_messages: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply a model-authored plan while preserving an exact audit transcript."""

    working_source = ensure_message_ids(working_messages)
    audit = ensure_message_ids(full_messages if full_messages is not None else working_source)
    audit_by_id = {str(message["_message_id"]): message for message in audit}
    blocks = context_blocks(working_source, protect_recent_turns=protect_recent_turns)
    raw_decisions = plan.get("blocks", []) if isinstance(plan, dict) else []
    decision_map = {
        str(item.get("block_id")): item
        for item in raw_decisions
        if isinstance(item, dict) and item.get("block_id")
    }
    output: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    summarized = elided = simplified_reasoning = 0

    def annotate(block: ContextBlock, status: str, reason: str, replacement: str = "") -> None:
        for message_id in block.message_ids:
            target = audit_by_id.get(message_id)
            if target is None:
                continue
            target["_context"] = {
                "status": status,
                "reason": reason,
                "block_id": block.id,
                "model_visible": status in {"active", "reasoning_simplified"},
                **({"replacement": replacement} if replacement else {}),
            }

    for block in blocks:
        decision = decision_map.get(block.id, {})
        action = str(decision.get("action") or "keep").casefold()
        reason = str(decision.get("reason") or "pressure_compactor_kept")
        summary = str(decision.get("summary") or "").strip()
        if block.kind == "system":
            action = "keep"
        if block.protected and action in {"elide", "summarize"}:
            action = "keep"
            reason = "recent_context_protected"
        if block.kind == "user_requirement" and action == "elide":
            action = "summarize" if summary else "keep"
            reason = "user_requirement_cannot_be_elided"
        if action not in {"keep", "summarize", "elide", "simplify_reasoning"}:
            action = "keep"
        if action in {"summarize", "simplify_reasoning"} and not summary:
            action = "keep"
            reason = "missing_summary_fallback_keep"

        if action == "elide":
            annotate(block, "pressure_elided", reason)
            elided += len(block.message_ids)
            ledger.append({"block_id": block.id, "kind": block.kind, "action": action, "reason": reason, "source_message_ids": list(block.message_ids)})
            continue
        if action == "simplify_reasoning" and block.kind == "assistant_reasoning":
            changed = False
            for message in block.messages:
                copied = copy.deepcopy(message)
                if copied.get("reasoning_content"):
                    copied["reasoning_content"] = summary
                    copied["_context"] = {"status": "reasoning_simplified", "reason": reason, "block_id": block.id}
                    changed = True
                output.append(copied)
            if changed:
                annotate(block, "reasoning_simplified", reason, summary)
                simplified_reasoning += 1
                ledger.append({"block_id": block.id, "kind": block.kind, "action": action, "reason": reason, "summary": summary, "source_message_ids": list(block.message_ids)})
                continue
        if action == "summarize":
            faithful = _faithful_summary(summary, block.messages)
            output.append({
                "role": "system",
                "name": "context_compactor",
                "content": faithful,
                "conversation_summary": True,
                "_context": {"status": "pressure_summary", "reason": reason, "block_id": block.id, "source_message_ids": list(block.message_ids)},
            })
            annotate(block, "pressure_summarized", reason, faithful)
            summarized += len(block.message_ids)
            ledger.append({"block_id": block.id, "kind": block.kind, "action": action, "reason": reason, "summary": faithful, "source_message_ids": list(block.message_ids)})
            continue

        output.extend(copy.deepcopy(message) for message in block.messages)
        annotate(block, "active", reason)
        ledger.append({"block_id": block.id, "kind": block.kind, "action": "keep", "reason": reason, "source_message_ids": list(block.message_ids)})

    fallback_used = False
    if estimate_tokens(output) > max(1, int(target_tokens)):
        continuation = str(plan.get("continuation_summary") or "").strip() if isinstance(plan, dict) else ""
        if continuation:
            protected_messages = [
                copy.deepcopy(message)
                for block in blocks if block.protected or block.kind == "system"
                for message in block.messages
            ]
            compactable_blocks = [block for block in blocks if not block.protected and block.kind != "system"]
            compactable_messages = [message for block in compactable_blocks for message in block.messages]
            faithful = _faithful_summary(continuation, compactable_messages)
            summary_message = {
                "role": "system",
                "name": "context_compactor",
                "content": faithful,
                "conversation_summary": True,
                "_context": {
                    "status": "pressure_summary",
                    "reason": "target_budget_fallback",
                    "source_message_ids": [message_id for block in compactable_blocks for message_id in block.message_ids],
                },
            }
            system_prefix = [message for message in protected_messages if message.get("role") == "system"]
            recent = [message for message in protected_messages if message.get("role") != "system"]
            output = system_prefix + [summary_message] + recent
            for block in compactable_blocks:
                annotate(block, "pressure_summarized", "target_budget_fallback", faithful)
            ledger.append({
                "block_id": "continuation_summary",
                "kind": "continuation_state",
                "action": "summarize",
                "reason": "target_budget_fallback",
                "summary": faithful,
                "source_message_ids": [message_id for block in compactable_blocks for message_id in block.message_ids],
            })
            fallback_used = True

    before_tokens = estimate_tokens(working_source)
    after_tokens = estimate_tokens(output)
    return {
        "messages": output,
        "full_messages": audit,
        "ledger": ledger,
        "stats": {
            "before_tokens_estimated": before_tokens,
            "after_tokens_estimated": after_tokens,
            "saved_tokens_estimated": max(0, before_tokens - after_tokens),
            "reduction_ratio": round(max(0, before_tokens - after_tokens) / max(1, before_tokens), 4),
            "summarized_messages": summarized,
            "elided_messages": elided,
            "simplified_reasoning_blocks": simplified_reasoning,
            "target_tokens": int(target_tokens),
            "target_fallback_used": fallback_used,
        },
    }


def judge_prompt(
    batch: Iterable[ConversationTurn],
    current_task: str = "",
    *,
    allow_summarize: bool = True,
) -> str:
    candidates = [turn.preview() for turn in batch]
    summarize_rule = (
        "- summarize: relevant but verbose material, repeated exploration, or large tool traces. Preserve exact "
        "facts, file paths, failures, decisions and unfinished work.\n"
        if allow_summarize else
        "- This pass is relevance pruning, not token-pressure compression. Do not summarize; use keep for relevant turns.\n"
    )
    actions = "keep|summarize|elide" if allow_summarize else "keep|elide"
    return (
        "You are EgoAgent's conservative context curator. Decide which OLD completed conversation turns "
        "are needed to continue the current project. The visible chat transcript is never deleted; your "
        "decision only controls the model's working context.\n\n"
        "Actions:\n"
        "- keep: project requirements, decisions, constraints, unresolved work, file paths, useful results, "
        "or anything uncertain.\n"
        + summarize_rule +
        "- elide: clearly unrelated casual Q&A, superseded noise, or failed/retried tool output whose cause and "
        "final outcome are already preserved elsewhere. Never elide a requirement or unresolved failure.\n\n"
        f"Current project request:\n{current_task[:4000]}\n\n"
        f"Candidate turns:\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"Return ONLY JSON: {{\"decisions\":[{{\"turn_id\":\"...\",\"action\":\"{actions}\","
        "\"reason\":\"short reason\",\"summary\":\"required for summarize, otherwise empty\"}]}"
    )
