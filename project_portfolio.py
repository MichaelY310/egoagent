"""Durable project and Session portfolio for the local EgoAgent product.

The runtime has always persisted Sessions, but older records were presented as
one global list.  This module makes the workspace relationship explicit without
moving or rewriting source Sessions.  It also stores small user-facing metadata
(pin/archive/title/active Session) separately from the immutable trajectory.

Runtime data lives below ``.egoagent`` and is intentionally not source control.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional


PORTFOLIO_SCHEMA = "ego.project-portfolio.v1"
_WORKING_DIRECTORY = re.compile(r"\[System\]\s+Working directory:\s*([^\r\n]+)")


def canonical_workspace(value: str | Path | None) -> str:
    """Return the stable absolute spelling used for identity comparisons."""

    if value is None or not str(value).strip():
        return ""
    return str(Path(value).expanduser().resolve())


def workspace_key(value: str | Path | None) -> str:
    canonical = canonical_workspace(value)
    return os.path.normcase(canonical).replace("\\", "/") if canonical else ""


def project_id_for_workspace(value: str | Path) -> str:
    key = workspace_key(value)
    if not key:
        raise ValueError("workspace is required")
    return "project_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_user_summary(session_dir: Path) -> str:
    for filename in ("full_messages.json", "messages.json"):
        try:
            messages = json.loads((session_dir / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(messages, list):
            continue
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content", "")
                if isinstance(content, str):
                    compact = " ".join(content.split())
                    if compact:
                        return compact[:160]
        break
    return ""


def infer_session_workspace(session_dir: Path) -> tuple[str, str]:
    """Return ``(workspace, provenance)`` for modern and legacy Sessions."""

    metadata = _read_json(session_dir / "session.json")
    recorded = str(metadata.get("workspace") or "").strip()
    if recorded:
        return canonical_workspace(recorded), "session.json"

    trajectory_path = session_dir / "trajectory.jsonl"
    try:
        with trajectory_path.open("r", encoding="utf-8") as stream:
            # Workspace is normally in trace.started.  Bound migration work so
            # a malformed legacy trace cannot make the portfolio view slow.
            for index, line in enumerate(stream):
                if index >= 64:
                    break
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                data = event.get("data") if isinstance(event, dict) else None
                workspace = str(data.get("workspace") or "").strip() if isinstance(data, dict) else ""
                if workspace:
                    return canonical_workspace(workspace), "trajectory"
    except OSError:
        pass

    for filename in ("full_messages.json", "messages.json"):
        try:
            messages = json.loads((session_dir / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(messages, list):
            continue
        for message in messages[:12]:
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                continue
            match = _WORKING_DIRECTORY.search(content)
            if match:
                return canonical_workspace(match.group(1).strip()), "message"
        break
    return "", "unknown"


class ProjectPortfolio:
    """Thread-safe registry plus a read-only projection of persisted Sessions."""

    def __init__(self, state_path: Path | str, sessions_root: Path | str):
        self.state_path = Path(state_path)
        self.sessions_root = Path(sessions_root)
        self._lock = threading.RLock()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema": PORTFOLIO_SCHEMA,
            "updated_at": 0.0,
            "projects": {},
            "sessions": {},
        }

    def _load(self) -> dict[str, Any]:
        payload = _read_json(self.state_path)
        if payload.get("schema") != PORTFOLIO_SCHEMA:
            payload = self._empty()
        payload.setdefault("projects", {})
        payload.setdefault("sessions", {})
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        payload["schema"] = PORTFOLIO_SCHEMA
        payload["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def register_project(
        self,
        workspace: Path | str,
        *,
        title: Optional[str] = None,
        touch: bool = True,
    ) -> dict[str, Any]:
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace does not exist: {path}")
        project_id = project_id_for_workspace(path)
        now = time.time()
        with self._lock:
            payload = self._load()
            existing = payload["projects"].get(project_id, {})
            record = {
                "id": project_id,
                "workspace": str(path),
                "title": str(title or existing.get("title") or path.name or str(path)),
                "description": str(existing.get("description") or ""),
                "tags": list(existing.get("tags") or []),
                "pinned": bool(existing.get("pinned", False)),
                "archived": bool(existing.get("archived", False)),
                "created_at": float(existing.get("created_at") or now),
                "last_opened_at": now if touch else float(existing.get("last_opened_at") or now),
                "active_session": str(existing.get("active_session") or ""),
            }
            payload["projects"][project_id] = record
            self._save(payload)
        return dict(record)

    def update_project(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "description", "tags", "pinned", "archived", "active_session"}
        with self._lock:
            payload = self._load()
            record = payload["projects"].get(str(project_id))
            if not isinstance(record, dict):
                raise KeyError(f"Project not found: {project_id}")
            for key in allowed:
                if key not in changes:
                    continue
                if key == "tags":
                    value = changes[key] if isinstance(changes[key], list) else []
                    record[key] = [str(item).strip() for item in value if str(item).strip()][:20]
                elif key in {"pinned", "archived"}:
                    record[key] = bool(changes[key])
                else:
                    record[key] = str(changes[key] or "").strip()[:500]
            record["last_opened_at"] = time.time()
            self._save(payload)
            return dict(record)

    def update_session(self, name: str, changes: dict[str, Any]) -> dict[str, Any]:
        session_dir = self._session_dir(name)
        workspace, _provenance = infer_session_workspace(session_dir)
        allowed = {"title", "pinned", "archived", "last_opened_at"}
        with self._lock:
            payload = self._load()
            existing = payload["sessions"].get(name, {})
            record = {
                "name": name,
                "project_id": project_id_for_workspace(workspace) if workspace else "unknown",
                "title": str(existing.get("title") or ""),
                "pinned": bool(existing.get("pinned", False)),
                "archived": bool(existing.get("archived", False)),
                "last_opened_at": float(existing.get("last_opened_at") or 0),
            }
            for key in allowed:
                if key not in changes:
                    continue
                if key in {"pinned", "archived"}:
                    record[key] = bool(changes[key])
                elif key == "last_opened_at":
                    record[key] = float(changes[key] or time.time())
                else:
                    record[key] = str(changes[key] or "").strip()[:500]
            if "last_opened_at" not in changes:
                record["last_opened_at"] = time.time()
            payload["sessions"][name] = record
            project = payload["projects"].get(record["project_id"])
            if isinstance(project, dict):
                project["active_session"] = name
                project["last_opened_at"] = time.time()
            self._save(payload)
            return dict(record)

    def _session_dir(self, name: str) -> Path:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Invalid session name")
        resolved = (self.sessions_root / name).resolve()
        try:
            resolved.relative_to(self.sessions_root.resolve())
        except ValueError as error:
            raise ValueError("Session escapes the sessions root") from error
        if not resolved.is_dir():
            raise FileNotFoundError(name)
        return resolved

    def _session_dirs(self) -> Iterable[Path]:
        if not self.sessions_root.is_dir():
            return ()
        return (item for item in self.sessions_root.iterdir() if item.is_dir())

    def list_sessions(
        self,
        *,
        workspace: Path | str | None = None,
        project_id: str = "",
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        requested_key = workspace_key(workspace)
        with self._lock:
            payload = self._load()
        custom = payload.get("sessions", {})
        result: list[dict[str, Any]] = []
        for directory in self._session_dirs():
            inferred_workspace, provenance = infer_session_workspace(directory)
            inferred_project = project_id_for_workspace(inferred_workspace) if inferred_workspace else "unknown"
            if requested_key and workspace_key(inferred_workspace) != requested_key:
                continue
            if project_id and inferred_project != project_id:
                continue
            local = custom.get(directory.name, {}) if isinstance(custom, dict) else {}
            if bool(local.get("archived", False)) and not include_archived:
                continue
            metadata = _read_json(directory / "session.json")
            working = self._message_count(directory / "messages.json")
            audit = self._message_count(directory / "full_messages.json") or working
            timestamp = max(
                float(directory.stat().st_mtime),
                float(metadata.get("updated_at") or 0),
            )
            result.append({
                "id": directory.name,
                "name": directory.name,
                "title": str(local.get("title") or ""),
                "path": str(directory),
                "workspace": inferred_workspace,
                "workspace_provenance": provenance,
                "project_id": inferred_project,
                "timestamp": timestamp,
                "message_count": audit,
                "working_message_count": working,
                "summary": _first_user_summary(directory),
                "harness": str(metadata.get("harness") or self._harness_from_name(directory.name)),
                "session_id": str(metadata.get("session_id") or ""),
                "trace_id": str(metadata.get("trace_id") or ""),
                "has_trajectory": (directory / "trajectory.jsonl").is_file(),
                "trajectory_events": int(metadata.get("trajectory_events") or 0),
                "trajectory_agents": list(metadata.get("trajectory_agents") or []),
                "health": metadata.get("health") if isinstance(metadata.get("health"), dict) else None,
                "pinned": bool(local.get("pinned", False)),
                "archived": bool(local.get("archived", False)),
                "last_opened_at": float(local.get("last_opened_at") or 0),
            })
        result.sort(key=lambda item: (bool(item["pinned"]), float(item["timestamp"])), reverse=True)
        return result[: max(1, min(int(limit), 5000))]

    def list_projects(
        self,
        *,
        current_workspace: Path | str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        if current_workspace:
            self.register_project(current_workspace)
        with self._lock:
            payload = self._load()
        projects = {
            key: dict(value)
            for key, value in payload.get("projects", {}).items()
            if isinstance(value, dict)
        }
        sessions = self.list_sessions(include_archived=True, limit=5000)
        aggregates: dict[str, dict[str, Any]] = {}
        for session in sessions:
            project_id = str(session["project_id"])
            aggregate = aggregates.setdefault(project_id, {"count": 0, "last": 0.0, "active": 0, "workspace": session["workspace"]})
            aggregate["count"] += 1
            aggregate["last"] = max(float(aggregate["last"]), float(session["timestamp"]))
            if not session["archived"]:
                aggregate["active"] += 1
        for project_id, aggregate in aggregates.items():
            if project_id == "unknown" or project_id in projects:
                continue
            workspace = str(aggregate.get("workspace") or "")
            projects[project_id] = {
                "id": project_id,
                "workspace": workspace,
                "title": Path(workspace).name if workspace else "Unassigned",
                "description": "",
                "tags": [],
                "pinned": False,
                "archived": False,
                "created_at": float(aggregate["last"]),
                "last_opened_at": float(aggregate["last"]),
                "active_session": "",
                "discovered": True,
            }
        if "unknown" in aggregates:
            projects["unknown"] = {
                "id": "unknown",
                "workspace": "",
                "title": "Unassigned legacy Sessions",
                "description": "Sessions created before workspace attribution was recorded.",
                "tags": ["legacy"],
                "pinned": False,
                "archived": False,
                "created_at": 0.0,
                "last_opened_at": float(aggregates["unknown"]["last"]),
                "active_session": "",
                "discovered": True,
            }
        discovered_records = {
            project_id: dict(record)
            for project_id, record in projects.items()
            if project_id != "unknown"
            and project_id not in payload.get("projects", {})
            and record.get("workspace")
            and Path(str(record["workspace"])).is_dir()
        }
        if discovered_records:
            with self._lock:
                persisted = self._load()
                for project_id, record in discovered_records.items():
                    record.pop("discovered", None)
                    persisted["projects"].setdefault(project_id, record)
                self._save(persisted)
        output = []
        current_key = workspace_key(current_workspace)
        for project_id, record in projects.items():
            if bool(record.get("archived", False)) and not include_archived:
                continue
            aggregate = aggregates.get(project_id, {})
            item = dict(record)
            item.update({
                "session_count": int(aggregate.get("count", 0)),
                "active_session_count": int(aggregate.get("active", 0)),
                "last_session_at": float(aggregate.get("last", 0)),
                "current": bool(current_key and workspace_key(record.get("workspace")) == current_key),
                "available": bool(record.get("workspace") and Path(str(record["workspace"])).is_dir()),
            })
            output.append(item)
        output.sort(
            key=lambda item: (
                bool(item.get("current")),
                bool(item.get("pinned")),
                max(float(item.get("last_opened_at") or 0), float(item.get("last_session_at") or 0)),
            ),
            reverse=True,
        )
        return output

    @staticmethod
    def _message_count(path: Path) -> int:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return 0
        return len(payload) if isinstance(payload, list) else 0

    @staticmethod
    def _harness_from_name(name: str) -> str:
        parts = name.split("_")
        if len(parts) >= 4 and parts[-3].isdigit() and parts[-2].isdigit():
            return "_".join(parts[:-3])
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            return "_".join(parts[:-2])
        return name


__all__ = [
    "PORTFOLIO_SCHEMA",
    "ProjectPortfolio",
    "canonical_workspace",
    "infer_session_workspace",
    "project_id_for_workspace",
    "workspace_key",
]
