"""Versioned semantic contracts for trajectory events.

The JSONL envelope remains forward-compatible: unknown extension events are
allowed, while core model/tool/conversation events have stable, testable
payload requirements shared by recording, replay and training export.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional


class EventCategory(str, Enum):
    TRACE = "trace"
    RUN = "run"
    NODE = "node"
    MODEL = "model"
    TOOL = "tool"
    CONVERSATION = "conversation"
    CONTEXT = "context"
    APPROVAL = "approval"
    SUBAGENT = "subagent"
    EVOLUTION = "evolution"
    CAPABILITY = "capability"
    RUNTIME = "runtime"
    EXTENSION = "extension"


@dataclass(frozen=True)
class EventDefinition:
    name: str
    category: EventCategory
    version: int = 1
    required_keys: tuple[str, ...] = ()
    typed_fields: tuple[tuple[str, type | tuple[type, ...]], ...] = ()
    terminal_for: Optional[str] = None


@dataclass(frozen=True)
class EventContractIssue:
    level: str
    message: str


def _definition(
    name: str,
    category: EventCategory,
    *,
    required: tuple[str, ...] = (),
    typed: tuple[tuple[str, type | tuple[type, ...]], ...] = (),
    terminal_for: Optional[str] = None,
) -> EventDefinition:
    return EventDefinition(name, category, 1, required, typed, terminal_for)


CORE_EVENT_DEFINITIONS = {
    item.name: item for item in (
        _definition("trace.started", EventCategory.TRACE, required=("workspace", "harness", "slots")),
        _definition("run.started", EventCategory.RUN),
        _definition("run.completed", EventCategory.RUN),
        _definition("run.cancelled", EventCategory.RUN),
        _definition("node.started", EventCategory.NODE),
        _definition("node.completed", EventCategory.NODE),
        _definition(
            "model.request",
            EventCategory.MODEL,
            required=("messages", "tools", "messages_sha256", "tools_sha256"),
            typed=(("messages", list), ("tools", list), ("parameters", dict)),
        ),
        _definition(
            "model.response",
            EventCategory.MODEL,
            required=("content", "tool_calls", "usage"),
            typed=(("tool_calls", list), ("usage", dict)),
            terminal_for="model.request",
        ),
        _definition(
            "model.error",
            EventCategory.MODEL,
            required=("error", "error_type"),
            terminal_for="model.request",
        ),
        _definition(
            "tool.request",
            EventCategory.TOOL,
            required=("name",),
        ),
        _definition(
            "tool.result",
            EventCategory.TOOL,
            required=("name", "status", "result"),
            terminal_for="tool.request",
        ),
        _definition(
            "conversation.working.append",
            EventCategory.CONVERSATION,
            required=("message", "context_generation"),
            typed=(("message", dict),),
        ),
        _definition(
            "conversation.audit.append",
            EventCategory.CONVERSATION,
            required=("message", "context_generation"),
            typed=(("message", dict),),
        ),
        _definition(
            "conversation.surface.replace",
            EventCategory.CONTEXT,
            required=("after_messages", "after_full_messages", "after_messages_sha256", "context_generation"),
            typed=(("after_messages", list), ("after_full_messages", list)),
        ),
        _definition("approval.requested", EventCategory.APPROVAL),
        _definition("approval.resolved", EventCategory.APPROVAL),
        _definition("subagent.spawned", EventCategory.SUBAGENT),
        _definition("subagent.completed", EventCategory.SUBAGENT),
        _definition("subagent.failed", EventCategory.SUBAGENT),
        _definition("context.compacted", EventCategory.CONTEXT),
        _definition(
            "capability.snapshot",
            EventCategory.CAPABILITY,
            required=("snapshot_id", "schema", "agent", "identity", "capabilities"),
            typed=(("identity", dict), ("capabilities", list)),
        ),
        _definition("capability.activated", EventCategory.CAPABILITY, required=("ref",)),
        _definition("evolution.proposed", EventCategory.EVOLUTION),
        _definition("evolution.evaluated", EventCategory.EVOLUTION),
        _definition("evolution.promoted", EventCategory.EVOLUTION),
        _definition("evolution.rolled_back", EventCategory.EVOLUTION),
        _definition("runtime.event", EventCategory.RUNTIME, required=("event", "payload")),
        _definition(
            "runtime.configuration.changed",
            EventCategory.RUNTIME,
            required=("previous", "current"),
            typed=(("previous", dict), ("current", dict)),
        ),
    )
}


_PREFIX_CATEGORIES = {
    "trace.": EventCategory.TRACE,
    "run.": EventCategory.RUN,
    "node.": EventCategory.NODE,
    "model.": EventCategory.MODEL,
    "tool.": EventCategory.TOOL,
    "conversation.": EventCategory.CONVERSATION,
    "context.": EventCategory.CONTEXT,
    "approval.": EventCategory.APPROVAL,
    "subagent.": EventCategory.SUBAGENT,
    "evolution.": EventCategory.EVOLUTION,
    "capability.": EventCategory.CAPABILITY,
    "runtime.": EventCategory.RUNTIME,
}


def event_definition(event_type: str) -> EventDefinition:
    name = str(event_type or "").strip()
    known = CORE_EVENT_DEFINITIONS.get(name)
    if known is not None:
        return known
    category = next(
        (value for prefix, value in _PREFIX_CATEGORIES.items() if name.startswith(prefix)),
        EventCategory.EXTENSION,
    )
    return EventDefinition(name=name, category=category)


def validate_event_contract(event_type: str, data: Any) -> list[EventContractIssue]:
    definition = CORE_EVENT_DEFINITIONS.get(str(event_type or ""))
    if definition is None:
        return []
    if not isinstance(data, Mapping):
        return [EventContractIssue("error", f"{definition.name} payload must be an object")]
    issues = []
    for key in definition.required_keys:
        if key not in data:
            issues.append(EventContractIssue("error", f"{definition.name} payload has no {key}"))
    for key, expected in definition.typed_fields:
        if key in data and not isinstance(data[key], expected):
            expected_name = "/".join(item.__name__ for item in expected) if isinstance(expected, tuple) else expected.__name__
            issues.append(EventContractIssue("error", f"{definition.name}.{key} must be {expected_name}"))
    return issues


def event_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "category": item.category.value,
            "version": item.version,
            "required_keys": list(item.required_keys),
            "terminal_for": item.terminal_for,
        }
        for item in sorted(CORE_EVENT_DEFINITIONS.values(), key=lambda value: value.name)
    ]


__all__ = [
    "CORE_EVENT_DEFINITIONS",
    "EventCategory",
    "EventContractIssue",
    "EventDefinition",
    "event_catalog",
    "event_definition",
    "validate_event_contract",
]
