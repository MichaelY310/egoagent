"""One lifecycle boundary shared by SubDAG nodes and create_harness tools."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

from runtime_contracts import SubagentInvocation, SubagentResult


def _identity_bindings(harness: Any) -> dict[str, str]:
    bindings = {}
    for slot, agent in (getattr(harness, "agents", {}) or {}).items():
        identity_path = getattr(getattr(agent, "identity", None), "identity_path", None)
        bindings[str(slot)] = Path(identity_path).name if identity_path else ""
    return bindings


def _emit_live_event(event: str, data: dict[str, Any]) -> None:
    """Project lifecycle events to the active UI without coupling to Studio.

    The trajectory remains authoritative. The active RunContext is only a live
    transport so Build/Task surfaces can show a child before its first model
    token arrives.
    """
    try:
        from harness import get_current_run_context
        context = get_current_run_context()
        if context is not None and callable(getattr(context, "emit", None)):
            context.emit(event, copy.deepcopy(data))
    except (ImportError, RuntimeError):
        return


def link_subagent(
    parent: Any,
    child: Any,
    *,
    share_session: bool = False,
    purpose: str = "subdag",
    agent_bindings: Optional[Mapping[str, str]] = None,
    identity_bindings: Optional[Mapping[str, str]] = None,
) -> SubagentInvocation:
    """Attach lineage and root trajectory before child execution starts."""

    invocation = SubagentInvocation(
        invocation_id=f"subagent_{uuid.uuid4().hex}",
        harness=str(getattr(child, "name", type(child).__name__)),
        parent_harness=str(getattr(parent, "name", "")) or None,
        workspace=Path(child.workspace).resolve() if getattr(child, "workspace", None) else None,
        share_session=bool(share_session),
        agent_bindings=dict(agent_bindings or {slot: getattr(agent, "name", slot) for slot, agent in (getattr(child, "agents", {}) or {}).items()}),
        identity_bindings=dict(identity_bindings or _identity_bindings(child)),
        purpose=str(purpose or "subdag"),
    )
    child.parent = parent
    if child not in parent.children:
        parent.children.append(child)
    if not share_session and getattr(parent, "session", None) is not None and getattr(child, "session", None) is not None:
        child.session.attach_trajectory(parent.session.trajectory)
    setattr(child, "_subagent_invocation", invocation)
    event_data = {
        "invocation_id": invocation.invocation_id,
        "child_harness": invocation.harness,
        "child_session_id": getattr(child.session, "session_id", None),
        "share_session": invocation.share_session,
        "purpose": invocation.purpose,
        "agent_bindings": copy.deepcopy(dict(invocation.agent_bindings)),
        "identity_bindings": copy.deepcopy(dict(invocation.identity_bindings)),
        "workspace": str(invocation.workspace) if invocation.workspace else None,
    }
    parent.session.trace("subagent.spawned", event_data)
    _emit_live_event("subagent_spawned", event_data)
    return invocation


def finish_subagent(child: Any, *, status: str, result: Any = None, error: Optional[BaseException | str] = None) -> SubagentResult:
    existing = getattr(child, "_subagent_result", None)
    if isinstance(existing, SubagentResult):
        return existing
    invocation = getattr(child, "_subagent_invocation", None)
    if invocation is None:
        invocation = SubagentInvocation(
            invocation_id=f"subagent_{uuid.uuid4().hex}",
            harness=str(getattr(child, "name", type(child).__name__)),
            parent_harness=str(getattr(getattr(child, "parent", None), "name", "")) or None,
            workspace=Path(child.workspace).resolve() if getattr(child, "workspace", None) else None,
        )
    parent = getattr(child, "parent", None)
    outcome = SubagentResult(
        invocation_id=invocation.invocation_id,
        status=str(status),
        result=copy.deepcopy(result),
        child_session_id=getattr(getattr(child, "session", None), "session_id", None),
        error=str(error) if error is not None else None,
    )
    target_session = getattr(parent, "session", None) or getattr(child, "session", None)
    event_data = {
        "invocation_id": invocation.invocation_id,
        "child_harness": invocation.harness,
        "child_session_id": outcome.child_session_id,
        "status": outcome.status,
        "result": copy.deepcopy(result),
        "error": outcome.error,
    }
    if target_session is not None:
        target_session.trace(
            "subagent.completed" if status == "completed" else "subagent.failed",
            event_data,
        )
    _emit_live_event("subagent_completed" if status == "completed" else "subagent_failed", event_data)
    setattr(child, "_subagent_result", outcome)
    return outcome
