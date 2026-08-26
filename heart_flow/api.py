"""Two optional HTTP hook functions for the isolated Heart Flow demo."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from .service import FlowRelayService, enabled


def _project(projects: list[dict[str, Any]], project_id: str) -> dict[str, Any]:
    match = next((item for item in projects if str(item.get("id")) == str(project_id)), None)
    if not match:
        raise ValueError(f"Project not found: {project_id}")
    return match


def _session(portfolio: Any, project_id: str, name: str) -> dict[str, Any] | None:
    sessions = portfolio.list_sessions(project_id=project_id, include_archived=True, limit=5000)
    if name:
        return next((item for item in sessions if item.get("name") == name), None)
    # Empty probe/evaluation directories are common and make a useless re-entry
    # capsule. Prefer the newest Session that contains an actual conversation.
    recent = sorted(sessions, key=lambda item: float(item.get("timestamp") or 0), reverse=True)
    return next((item for item in recent if int(item.get("message_count") or 0) > 0), recent[0] if recent else None)


def handle_get(handler: Any, path: str, parsed_url: Any, *, service: FlowRelayService, portfolio: Any, runs: Any) -> bool:
    if path != "/api/heart-flow/status":
        return False
    query = parse_qs(parsed_url.query)
    workspace = (query.get("workspace") or [None])[0]
    projects = portfolio.list_projects(current_workspace=workspace, include_archived=False)
    handler._send_json(service.snapshot(projects=projects, runs=runs.list()))
    return True


def handle_post(handler: Any, path: str, *, service: FlowRelayService, portfolio: Any, runs: Any) -> bool:
    if not path.startswith("/api/heart-flow/"):
        return False
    if not enabled():
        handler._send_error("Heart Flow demo is disabled", 404)
        return True
    body = handler._read_body()
    projects = portfolio.list_projects(include_archived=False)
    try:
        if path == "/api/heart-flow/focus":
            project_id = str(body.get("project_id") or "")
            _project(projects, project_id)
            focus = service.focus(project_id, minutes=body.get("minutes"))
            handler._send_json({"ok": True, "focus": focus})
            return True
        if path == "/api/heart-flow/stop":
            handler._send_json({"ok": True, "focus": service.focus("")})
            return True
        if path == "/api/heart-flow/park":
            project_id = str(body.get("project_id") or "")
            project = _project(projects, project_id)
            session_name = str(body.get("session") or "")
            selected = _session(portfolio, project_id, session_name)
            if session_name and not selected:
                raise ValueError(f"Session not found in Project: {session_name}")
            capsule = service.park(project=project, session=selected, overrides=body.get("capsule"))
            handler._send_json({"ok": True, "capsule": capsule})
            return True
        if path == "/api/heart-flow/settings":
            handler._send_json({"ok": True, "settings": service.update_settings(body)})
            return True
        if path == "/api/heart-flow/inbox/ack":
            event_ids = body.get("event_ids") if isinstance(body.get("event_ids"), list) else []
            handler._send_json({"ok": True, "acknowledged": service.acknowledge(event_ids)})
            return True
    except (OSError, ValueError, TypeError) as error:
        handler._send_error(str(error), 400)
        return True
    handler._send_error("Heart Flow endpoint not found", 404)
    return True


__all__ = ["FlowRelayService", "enabled", "handle_get", "handle_post"]
