"""Append-only EgoAgent trajectory recording, replay and training export.

The trajectory is the durable audit record for *what happened*.  Legacy
``messages.json``/``full_messages.json`` files remain fast projections while
new runs additionally record exact model views, runtime events, context
surface replacements and multi-run lineage in one root JSONL stream.

This module deliberately has no dependency on the Pipeline or HTTP server so
it can be reused by CLI runs, tests and future SDK frontends.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from event_protocol import event_definition, validate_event_contract


EVENT_SCHEMA = "ego.trajectory.event.v1"
EVENT_FORMAT_VERSION = 1
MODEL_CALL_SCHEMA = "ego.model-call.v1"
EXPORT_MANIFEST_SCHEMA = "ego.trajectory-export.v1"
COLLECTION_SETTINGS_SCHEMA = "ego.trajectory-collection.v1"
PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / ".egoagent" / "trajectory_collection.json"
_SETTINGS_LOCK = threading.RLock()
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)[^\s,;\"']{8,}"),
)
_SENSITIVE_KEYS = {"authorization", "api_key", "apikey", "access_token", "refresh_token", "password", "secret"}


def _json_value(value: Any) -> Any:
    """Return a deterministic JSON-compatible copy without executing hooks."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def redact_sensitive_value(value: Any) -> tuple[Any, int]:
    """Best-effort disk boundary redaction independent of active RunContext."""
    if isinstance(value, dict):
        result = {}
        count = 0
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or normalized.endswith("_api_key") or normalized.endswith("_password"):
                result[str(key)] = "[REDACTED]"
                count += 1
            else:
                redacted, child_count = redact_sensitive_value(child)
                result[str(key)] = redacted
                count += child_count
        return result, count
    if isinstance(value, (list, tuple, set)):
        items = []
        count = 0
        for child in value:
            redacted, child_count = redact_sensitive_value(child)
            items.append(redacted)
            count += child_count
        return items, count
    if isinstance(value, str):
        text = value
        count = 0
        for pattern in _SECRET_TEXT_PATTERNS:
            if pattern.groups:
                text, replacements = pattern.subn(lambda match: f"{match.group(1)}[REDACTED]", text)
            else:
                text, replacements = pattern.subn("[REDACTED]", text)
            count += replacements
        return text, count
    return value, 0


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def messages_sha256(messages: Any) -> str:
    return payload_sha256(messages if isinstance(messages, list) else [])


def _is_filesystem_root(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == Path(resolved.anchor)


def default_collection_settings() -> dict[str, Any]:
    return {
        "schema": COLLECTION_SETTINGS_SCHEMA,
        "enabled": False,
        "destination": "",
        "partition_by_date": True,
        "partition_by_project": True,
        "updated_at": None,
    }


def load_collection_settings(path: Optional[Path] = None) -> dict[str, Any]:
    path = SETTINGS_PATH if path is None else Path(path)
    settings = default_collection_settings()
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return settings
    if not isinstance(payload, dict):
        return settings
    settings.update({key: payload[key] for key in settings if key in payload})
    settings["enabled"] = bool(settings.get("enabled"))
    settings["destination"] = str(settings.get("destination") or "")
    settings["partition_by_date"] = bool(settings.get("partition_by_date", True))
    settings["partition_by_project"] = bool(settings.get("partition_by_project", True))
    return settings


def save_collection_settings(
    *,
    enabled: bool,
    destination: str = "",
    partition_by_date: bool = True,
    partition_by_project: bool = True,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    path = SETTINGS_PATH if path is None else Path(path)
    destination = str(destination or "").strip()
    resolved_destination: Optional[Path] = None
    if enabled:
        if not destination:
            raise ValueError("A collection destination is required when trajectory mirroring is enabled")
        resolved_destination = Path(destination).expanduser().resolve()
        if _is_filesystem_root(resolved_destination):
            raise ValueError("The collection destination cannot be a filesystem root")
        resolved_destination.mkdir(parents=True, exist_ok=True)
        if not resolved_destination.is_dir():
            raise ValueError("The collection destination must be a directory")
        probe = resolved_destination / f".egoagent-write-probe-{uuid.uuid4().hex}"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            raise ValueError(f"The collection destination is not writable: {error}") from error
    payload = {
        "schema": COLLECTION_SETTINGS_SCHEMA,
        "enabled": bool(enabled),
        "destination": str(resolved_destination) if resolved_destination else destination,
        "partition_by_date": bool(partition_by_date),
        "partition_by_project": bool(partition_by_project),
        "updated_at": time.time(),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with _SETTINGS_LOCK:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    return payload


@dataclass(frozen=True)
class TrajectoryLocation:
    native_path: Optional[Path]
    mirror_path: Optional[Path]
    trace_id: str


@dataclass(frozen=True)
class SessionHealth:
    status: str
    replayable: bool
    training_ready: bool
    event_count: int
    model_calls: int
    tool_calls: int
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    durability_error: Optional[str] = None
    mirror_error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "replayable": self.replayable,
            "training_ready": self.training_ready,
            "event_count": self.event_count,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "durability_error": self.durability_error,
            "mirror_error": self.mirror_error,
        }


class TrajectoryRecorder:
    """Thread-safe root recorder shared by a parent run and all descendants."""

    def __init__(
        self,
        native_path: Optional[Path],
        *,
        trace_id: Optional[str] = None,
        project_root: Optional[Path] = None,
        project_name: Optional[str] = None,
    ) -> None:
        self.native_path = Path(native_path).resolve() if native_path else None
        self.trace_id = str(trace_id or f"trace_{uuid.uuid4().hex}")
        self.project_root = Path(project_root or PROJECT_ROOT).resolve()
        self.project_name = str(project_name or self.project_root.name or "egoagent")
        self._lock = threading.RLock()
        self._sequence = 0
        self._event_ids: set[str] = set()
        self._capability_snapshot_ids: set[str] = set()
        self._agents: set[str] = set()
        self._last_error: Optional[str] = None
        self._mirror_error: Optional[str] = None
        self._settings_checked_at = 0.0
        self._settings_mtime_ns: Optional[int] = None
        self._settings = default_collection_settings()
        self._mirror_path: Optional[Path] = None
        if self.native_path and self.native_path.exists():
            self._restore_tail()
        self._refresh_mirror(force=True)

    @property
    def location(self) -> TrajectoryLocation:
        return TrajectoryLocation(self.native_path, self._mirror_path, self.trace_id)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def mirror_error(self) -> Optional[str]:
        return self._mirror_error

    @property
    def event_count(self) -> int:
        return self._sequence

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    @property
    def capability_snapshot_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._capability_snapshot_ids))

    def _restore_tail(self) -> None:
        try:
            reader = TrajectoryReader(self.native_path)
            events = reader.read_all(strict=False)
            if events:
                self._sequence = max(int(event.get("sequence", 0)) for event in events)
                self._event_ids = {str(event.get("event_id")) for event in events if event.get("event_id")}
                self._capability_snapshot_ids = {
                    str((event.get("data") or {}).get("snapshot_id"))
                    for event in events
                    if event.get("type") == "capability.snapshot"
                    and isinstance(event.get("data"), dict)
                    and (event.get("data") or {}).get("snapshot_id")
                }
                self._agents = {str(event.get("agent")) for event in events if event.get("agent")}
                existing_trace = next((str(event.get("trace_id")) for event in events if event.get("trace_id")), None)
                if existing_trace:
                    self.trace_id = existing_trace
        except (OSError, ValueError, TypeError):
            # Appending still works; validation will surface malformed history.
            return

    def _refresh_mirror(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._settings_checked_at < 2.0:
            return
        self._settings_checked_at = now
        try:
            mtime_ns = SETTINGS_PATH.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        if not force and mtime_ns == self._settings_mtime_ns:
            return
        self._settings_mtime_ns = mtime_ns
        self._settings = load_collection_settings()
        self._mirror_path = None
        self._mirror_error = None
        if not self._settings.get("enabled"):
            return
        try:
            destination = Path(str(self._settings.get("destination") or "")).expanduser().resolve()
            if not destination or _is_filesystem_root(destination):
                raise ValueError("unsafe or empty mirror destination")
            if self._settings.get("partition_by_date", True):
                destination /= datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._settings.get("partition_by_project", True):
                safe_project = "".join(
                    char if char.isalnum() or char in "-_." else "-" for char in self.project_name
                ).strip("-.") or "project"
                destination /= safe_project
            destination.mkdir(parents=True, exist_ok=True)
            self._mirror_path = destination / f"{self.trace_id}.jsonl"
        except (OSError, ValueError) as error:
            self._mirror_error = str(error)

    @staticmethod
    def _append_line(path: Path, event: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.flush()

    def append(
        self,
        event_type: str,
        data: Any = None,
        *,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        harness: Optional[str] = None,
        node_id: Optional[str] = None,
        node_op: Optional[str] = None,
        agent: Optional[str] = None,
        identity: Optional[str] = None,
        model_call_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Append one immutable event and return it.

        Native trace failures are exposed through ``last_error`` but do not
        crash an Agent task.  The caller can surface the diagnostic and tests
        can enforce strict durability where required.
        """

        event_type = str(event_type or "").strip()
        if not event_type:
            raise ValueError("trajectory event type cannot be empty")
        payload = _json_value(data if data is not None else {})
        payload, redaction_count = redact_sensitive_value(payload)
        if event_type == "model.request" and redaction_count and isinstance(payload, dict):
            payload["messages_sha256"] = messages_sha256(payload.get("messages") or [])
            payload["tools_sha256"] = payload_sha256(payload.get("tools") or [])
        definition = event_definition(event_type)
        contract_issues = validate_event_contract(event_type, payload)
        contract_errors = [issue.message for issue in contract_issues if issue.level == "error"]
        if contract_errors:
            raise ValueError("; ".join(contract_errors))
        with self._lock:
            self._sequence += 1
            event_id = f"evt_{uuid.uuid4().hex}"
            event = {
                "schema": EVENT_SCHEMA,
                "format_version": EVENT_FORMAT_VERSION,
                "event_id": event_id,
                "sequence": self._sequence,
                "timestamp": time.time(),
                "trace_id": self.trace_id,
                "session_id": session_id,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "harness": harness,
                "node_id": node_id,
                "node_op": node_op,
                "agent": agent,
                "identity": identity,
                "model_call_id": model_call_id,
                "tool_call_id": tool_call_id,
                "type": event_type,
                "event_version": definition.version,
                "category": definition.category.value,
                "tags": sorted({str(tag) for tag in (tags or []) if str(tag)}),
                "data": payload,
            }
            if redaction_count:
                event["redaction"] = {
                    "count": redaction_count,
                    "policy": "ego.trajectory-secret-redaction.v1",
                }
            event["integrity"] = {"payload_sha256": payload_sha256(event)}
            if self.native_path is not None:
                try:
                    self._append_line(self.native_path, event)
                    self._last_error = None
                except OSError as error:
                    self._last_error = str(error)
            self._refresh_mirror()
            if self._mirror_path is not None:
                try:
                    self._append_line(self._mirror_path, event)
                    self._mirror_error = None
                except OSError as error:
                    self._mirror_error = str(error)
            self._event_ids.add(event_id)
            if agent:
                self._agents.add(str(agent))
            return copy.deepcopy(event)

    def register_capability_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        harness: Optional[str] = None,
        agent: Optional[str] = None,
        identity: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Write a content-addressed snapshot once per root trajectory."""

        snapshot_id = str((snapshot or {}).get("snapshot_id") or "")
        if not snapshot_id:
            raise ValueError("capability snapshot has no snapshot_id")
        with self._lock:
            if snapshot_id in self._capability_snapshot_ids:
                return None
            event = self.append(
                "capability.snapshot",
                snapshot,
                session_id=session_id,
                run_id=run_id,
                harness=harness,
                agent=agent,
                identity=identity,
            )
            self._capability_snapshot_ids.add(snapshot_id)
            return event


class TrajectoryReader:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def iter_events(self, *, strict: bool = True) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError as error:
                    if strict:
                        raise ValueError(f"invalid trajectory JSON at line {line_number}: {error}") from error
                    continue
                if not isinstance(event, dict):
                    if strict:
                        raise ValueError(f"trajectory line {line_number} is not an object")
                    continue
                yield event

    def read_all(self, *, strict: bool = True) -> list[dict[str, Any]]:
        return list(self.iter_events(strict=strict) or [])

    def events(
        self,
        *,
        after: int = 0,
        limit: int = 1000,
        event_types: Optional[Iterable[str]] = None,
        agents: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        allowed_types = {str(value) for value in (event_types or []) if str(value)}
        allowed_agents = {str(value) for value in (agents or []) if str(value)}
        selected = []
        for event in self.iter_events(strict=False) or []:
            if int(event.get("sequence", 0)) <= int(after):
                continue
            if allowed_types and str(event.get("type")) not in allowed_types:
                continue
            if allowed_agents and str(event.get("agent")) not in allowed_agents:
                continue
            selected.append(event)
            if len(selected) >= max(1, min(int(limit), 10000)):
                break
        return selected

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        seen_ids: set[str] = set()
        last_sequence = 0
        requests: dict[str, dict[str, Any]] = {}
        responses: dict[str, dict[str, Any]] = {}
        model_errors: dict[str, dict[str, Any]] = {}
        tool_requests: dict[str, dict[str, Any]] = {}
        tool_results: dict[str, dict[str, Any]] = {}
        surfaces: dict[str, dict[str, list[dict[str, Any]]]] = {}
        event_count = 0
        trace_ids: set[str] = set()
        for event in self.iter_events(strict=False) or []:
            event_count += 1
            sequence = int(event.get("sequence", 0) or 0)
            schema = str(event.get("schema") or "")
            if schema != EVENT_SCHEMA:
                errors.append(f"sequence {sequence} has unsupported schema {schema or '<missing>'}")
            format_version = event.get("format_version")
            if format_version is None:
                warnings.append(f"sequence {sequence} predates explicit format_version")
            elif format_version != EVENT_FORMAT_VERSION:
                errors.append(
                    f"sequence {sequence} has unsupported format_version {format_version!r}"
                )
            if sequence <= last_sequence:
                errors.append(f"sequence {sequence} is not strictly greater than {last_sequence}")
            last_sequence = max(last_sequence, sequence)
            event_id = str(event.get("event_id") or "")
            if not event_id:
                errors.append(f"sequence {sequence} has no event_id")
            elif event_id in seen_ids:
                errors.append(f"duplicate event_id {event_id}")
            seen_ids.add(event_id)
            trace_id = str(event.get("trace_id") or "")
            if trace_id:
                trace_ids.add(trace_id)
            expected = str((event.get("integrity") or {}).get("payload_sha256") or "")
            unhashed = {key: value for key, value in event.items() if key != "integrity"}
            if not expected:
                errors.append(f"sequence {sequence} has no payload integrity hash")
            elif payload_sha256(unhashed) != expected:
                errors.append(f"sequence {sequence} failed payload integrity")
            event_type = event.get("type")
            definition = event_definition(str(event_type or ""))
            event_version = event.get("event_version")
            if event_version is None:
                warnings.append(f"sequence {sequence} predates typed event_version")
            elif event_version != definition.version:
                errors.append(
                    f"sequence {sequence} event {event_type} has unsupported event_version {event_version!r}"
                )
            category = event.get("category")
            if category is None:
                warnings.append(f"sequence {sequence} predates typed event category")
            elif str(category) != definition.category.value:
                errors.append(
                    f"sequence {sequence} event {event_type} category {category!r} should be {definition.category.value!r}"
                )
            session_id = str(event.get("session_id") or "")
            event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
            for issue in validate_event_contract(str(event_type or ""), event.get("data")):
                target = errors if issue.level == "error" else warnings
                target.append(f"sequence {sequence}: {issue.message}")
            if session_id and event_type in {
                "conversation.working.append",
                "conversation.audit.append",
                "conversation.surface.replace",
            }:
                surface = surfaces.setdefault(session_id, {"working": [], "audit": []})
                if event_type == "conversation.working.append" and isinstance(event_data.get("message"), dict):
                    surface["working"].append(copy.deepcopy(event_data["message"]))
                elif event_type == "conversation.audit.append" and isinstance(event_data.get("message"), dict):
                    surface["audit"].append(copy.deepcopy(event_data["message"]))
                elif event_type == "conversation.surface.replace":
                    expected_before = str(event_data.get("before_messages_sha256") or "")
                    if expected_before and messages_sha256(surface["working"]) != expected_before:
                        errors.append(
                            f"conversation surface replacement at {sequence} does not match prior working history"
                        )
                    expected_before_full = str(event_data.get("before_full_messages_sha256") or "")
                    if expected_before_full and messages_sha256(surface["audit"]) != expected_before_full:
                        errors.append(
                            f"conversation surface replacement at {sequence} does not match prior audit history"
                        )
                    after_messages = event_data.get("after_messages")
                    after_full_messages = event_data.get("after_full_messages")
                    if isinstance(after_messages, list):
                        surface["working"] = copy.deepcopy(after_messages)
                    if isinstance(after_full_messages, list):
                        surface["audit"] = copy.deepcopy(after_full_messages)
                    expected_after = str(event_data.get("after_messages_sha256") or "")
                    if expected_after and messages_sha256(surface["working"]) != expected_after:
                        errors.append(f"conversation surface replacement at {sequence} failed working hash")
                    expected_after_full = str(event_data.get("after_full_messages_sha256") or "")
                    if expected_after_full and messages_sha256(surface["audit"]) != expected_after_full:
                        errors.append(f"conversation surface replacement at {sequence} failed audit hash")
            call_id = str(event.get("model_call_id") or "")
            if event_type == "model.request":
                if not call_id:
                    errors.append(f"model.request at {sequence} has no model_call_id")
                elif call_id in requests:
                    errors.append(f"duplicate model.request {call_id}")
                else:
                    requests[call_id] = event
                request_data = event.get("data") if isinstance(event.get("data"), dict) else {}
                expected_messages = str(request_data.get("messages_sha256") or "")
                if not expected_messages:
                    errors.append(f"model.request {call_id or sequence} has no messages hash")
                elif messages_sha256(request_data.get("messages") or []) != expected_messages:
                    errors.append(f"model.request {call_id or sequence} failed messages integrity")
                expected_tools = str(request_data.get("tools_sha256") or "")
                if not expected_tools:
                    errors.append(f"model.request {call_id or sequence} has no tools hash")
                elif payload_sha256(request_data.get("tools") or []) != expected_tools:
                    errors.append(f"model.request {call_id or sequence} failed tools integrity")
                for field in ("run_id", "harness", "agent", "identity"):
                    if event.get(field) in (None, ""):
                        warnings.append(f"model.request {call_id or sequence} has no {field}")
            elif event_type == "model.response":
                if not call_id:
                    errors.append(f"model.response at {sequence} has no model_call_id")
                elif call_id in responses:
                    errors.append(f"duplicate model.response {call_id}")
                else:
                    responses[call_id] = event
            elif event_type == "model.error":
                if not call_id:
                    errors.append(f"model.error at {sequence} has no model_call_id")
                elif call_id in model_errors:
                    errors.append(f"duplicate model.error {call_id}")
                else:
                    model_errors[call_id] = event
            elif event_type == "tool.request":
                tool_call_id = str(event.get("tool_call_id") or "")
                if not tool_call_id:
                    errors.append(f"tool.request at {sequence} has no tool_call_id")
                elif tool_call_id in tool_requests:
                    errors.append(f"duplicate tool.request {tool_call_id}")
                else:
                    tool_requests[tool_call_id] = event
            elif event_type == "tool.result":
                tool_call_id = str(event.get("tool_call_id") or "")
                if not tool_call_id:
                    errors.append(f"tool.result at {sequence} has no tool_call_id")
                elif tool_call_id in tool_results:
                    errors.append(f"duplicate tool.result {tool_call_id}")
                else:
                    tool_results[tool_call_id] = event
        for call_id in responses:
            if call_id not in requests:
                errors.append(f"model.response {call_id} has no request")
        for call_id in model_errors:
            if call_id not in requests:
                errors.append(f"model.error {call_id} has no request")
        for call_id, response in {**responses, **model_errors}.items():
            request = requests.get(call_id)
            if request is None:
                continue
            if int(response.get("sequence", 0) or 0) <= int(request.get("sequence", 0) or 0):
                errors.append(f"model terminal event {call_id} does not follow its request")
            for field in ("trace_id", "session_id", "run_id", "agent"):
                left = request.get(field)
                right = response.get(field)
                if left not in (None, "") and right not in (None, "") and left != right:
                    errors.append(f"model call {call_id} changes {field} between request and terminal event")
        for tool_call_id, result in tool_results.items():
            request = tool_requests.get(tool_call_id)
            if request is None:
                errors.append(f"tool.result {tool_call_id} has no request")
            elif int(result.get("sequence", 0) or 0) <= int(request.get("sequence", 0) or 0):
                errors.append(f"tool.result {tool_call_id} does not follow its request")
        incomplete = sorted(
            call_id for call_id in requests if call_id not in responses and call_id not in model_errors
        )
        incomplete_tools = sorted(call_id for call_id in tool_requests if call_id not in tool_results)
        if len(trace_ids) > 1:
            errors.append(f"trajectory file contains multiple trace_ids: {sorted(trace_ids)}")
        return {
            "valid": not errors,
            "events": event_count,
            "last_sequence": last_sequence,
            "trace_id": next(iter(trace_ids), None),
            "model_requests": len(requests),
            "model_responses": len(responses),
            "model_errors": len(model_errors),
            "incomplete_model_calls": incomplete,
            "tool_requests": len(tool_requests),
            "tool_results": len(tool_results),
            "incomplete_tool_calls": incomplete_tools,
            "errors": errors,
            "warnings": warnings,
        }

    def model_calls(self, *, include_incomplete: bool = False) -> list[dict[str, Any]]:
        requests: dict[str, dict[str, Any]] = {}
        responses: dict[str, dict[str, Any]] = {}
        errors: dict[str, dict[str, Any]] = {}
        for event in self.iter_events(strict=False) or []:
            call_id = str(event.get("model_call_id") or "")
            if not call_id:
                continue
            if event.get("type") == "model.request":
                requests[call_id] = event
            elif event.get("type") == "model.response":
                responses[call_id] = event
            elif event.get("type") == "model.error":
                errors[call_id] = event
        result = []
        for call_id, request in sorted(requests.items(), key=lambda item: int(item[1].get("sequence", 0))):
            response = responses.get(call_id)
            if response is None and not include_incomplete:
                continue
            request_data = copy.deepcopy(request.get("data") or {})
            response_data = copy.deepcopy((response or errors.get(call_id) or {}).get("data") or {})
            result.append({
                "schema": MODEL_CALL_SCHEMA,
                "model_call_id": call_id,
                "messages": request_data.get("messages") or [],
                "tools": request_data.get("tools") or [],
                "parameters": request_data.get("parameters") or {},
                "response": {
                    "content": response_data.get("content", response_data.get("text", "")),
                    "reasoning": response_data.get("reasoning", ""),
                    "tool_calls": response_data.get("tool_calls") or [],
                    "finish_reason": response_data.get("finish_reason"),
                    "usage": response_data.get("usage") or {},
                    "error": response_data.get("error"),
                },
                "metadata": {
                    "model_call_id": call_id,
                    "trace_id": request.get("trace_id"),
                    "session_id": request.get("session_id"),
                    "run_id": request.get("run_id"),
                    "parent_run_id": request.get("parent_run_id"),
                    "harness": request.get("harness"),
                    "node": request.get("node_id"),
                    "node_op": request.get("node_op"),
                    "agent": request.get("agent"),
                    "identity": request.get("identity"),
                    "model": request_data.get("model"),
                    "provider": request_data.get("provider"),
                    "purpose": request_data.get("purpose"),
                    "request_sequence": request.get("sequence"),
                    "response_sequence": response.get("sequence") if response else None,
                    "messages_sha256": request_data.get("messages_sha256") or messages_sha256(request_data.get("messages")),
                },
            })
        return result

    def health(
        self,
        *,
        durability_error: Optional[str] = None,
        mirror_error: Optional[str] = None,
    ) -> SessionHealth:
        validation = self.validate()
        blockers = list(validation.get("errors", []))
        incomplete_models = list(validation.get("incomplete_model_calls", []))
        incomplete_tools = list(validation.get("incomplete_tool_calls", []))
        if durability_error:
            blockers.append(f"trajectory persistence failed: {durability_error}")
        if incomplete_models:
            blockers.append(f"{len(incomplete_models)} model call(s) have no terminal event")
        if incomplete_tools:
            blockers.append(f"{len(incomplete_tools)} tool call(s) have no result")
        if validation.get("errors") or durability_error:
            status = "invalid"
        elif incomplete_models or incomplete_tools:
            status = "incomplete"
        elif validation.get("warnings") or mirror_error:
            status = "degraded"
        else:
            status = "healthy"
        event_count = int(validation.get("events", 0) or 0)
        complete_model_calls = min(
            int(validation.get("model_requests", 0) or 0),
            int(validation.get("model_responses", 0) or 0) + int(validation.get("model_errors", 0) or 0),
        )
        return SessionHealth(
            status=status,
            replayable=bool(event_count and not validation.get("errors") and not durability_error),
            training_ready=bool(
                complete_model_calls
                and not validation.get("errors")
                and not durability_error
                and not incomplete_models
                and not incomplete_tools
            ),
            event_count=event_count,
            model_calls=complete_model_calls,
            tool_calls=int(validation.get("tool_results", 0) or 0),
            blockers=tuple(blockers),
            warnings=tuple(validation.get("warnings", [])),
            durability_error=durability_error,
            mirror_error=mirror_error,
        )

    def summary(self) -> dict[str, Any]:
        events = self.read_all(strict=False)
        agents = sorted({str(event.get("agent")) for event in events if event.get("agent")})
        identities = sorted({str(event.get("identity")) for event in events if event.get("identity")})
        runs = sorted({str(event.get("run_id")) for event in events if event.get("run_id")})
        harnesses = sorted({str(event.get("harness")) for event in events if event.get("harness")})
        types: dict[str, int] = {}
        for event in events:
            event_type = str(event.get("type") or "unknown")
            types[event_type] = types.get(event_type, 0) + 1
        model_calls = self.model_calls(include_incomplete=True)
        return {
            "path": str(self.path),
            "trace_id": next((event.get("trace_id") for event in events if event.get("trace_id")), None),
            "events": len(events),
            "first_timestamp": events[0].get("timestamp") if events else None,
            "last_timestamp": events[-1].get("timestamp") if events else None,
            "agents": agents,
            "identities": identities,
            "runs": runs,
            "harnesses": harnesses,
            "model_calls": len(model_calls),
            "event_types": dict(sorted(types.items())),
            "validation": self.validate(),
            "health": self.health().as_dict(),
        }

    def reconstruct_session(self, session_id: str) -> dict[str, Any]:
        """Project one Session surface from a possibly multi-Session root trace."""

        working: list[dict[str, Any]] = []
        audit: list[dict[str, Any]] = []
        generation = 0
        applied = 0
        for event in self.iter_events(strict=False) or []:
            if str(event.get("session_id") or "") != str(session_id):
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            event_type = event.get("type")
            if event_type == "conversation.working.append" and isinstance(data.get("message"), dict):
                working.append(copy.deepcopy(data["message"]))
                applied += 1
            elif event_type == "conversation.audit.append" and isinstance(data.get("message"), dict):
                audit.append(copy.deepcopy(data["message"]))
                applied += 1
            elif event_type == "conversation.surface.replace":
                after = data.get("after_messages")
                if isinstance(after, list):
                    working = copy.deepcopy(after)
                    applied += 1
                after_full = data.get("after_full_messages")
                if isinstance(after_full, list):
                    audit = copy.deepcopy(after_full)
            try:
                generation = max(generation, int(data.get("context_generation", 0) or 0))
            except (TypeError, ValueError):
                pass
        return {
            "session_id": str(session_id),
            "messages": working,
            "full_messages": audit or copy.deepcopy(working),
            "context_generation": generation,
            "applied_events": applied,
        }


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str)


def _sharegpt_sample(call: dict[str, Any], *, include_reasoning: bool = False) -> dict[str, Any]:
    systems = []
    conversations = []
    for message in call.get("messages", []):
        role = str(message.get("role") or "user")
        value = _message_content(message)
        if role == "system":
            systems.append(value)
            continue
        if role == "assistant":
            tag = "gpt"
            if message.get("tool_calls"):
                value = json.dumps(
                    {"content": value, "tool_calls": message.get("tool_calls")},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        elif role == "tool":
            tag = "observation"
        else:
            tag = "human"
        conversations.append({"from": tag, "value": value})
    response = call.get("response") or {}
    target = str(response.get("content") or "")
    if include_reasoning and response.get("reasoning"):
        target = f"<think>{response['reasoning']}</think>\n{target}"
    if response.get("tool_calls"):
        target = json.dumps(
            {"content": target, "tool_calls": response.get("tool_calls")},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    conversations.append({"from": "gpt", "value": target})
    return {
        "conversations": conversations,
        "system": "\n\n".join(value for value in systems if value),
        "tools": json.dumps(call.get("tools") or [], ensure_ascii=False, separators=(",", ":")),
        "metadata": copy.deepcopy(call.get("metadata") or {}),
    }


def export_training_data(
    trajectory_path: Path | str,
    destination: Path | str,
    *,
    include_reasoning: bool = False,
    include_incomplete: bool = False,
) -> dict[str, Any]:
    """Export canonical, LLaMA-Factory and verl-compatible JSONL datasets."""

    reader = TrajectoryReader(trajectory_path)
    validation = reader.validate()
    if not validation["valid"]:
        raise ValueError("Cannot export an invalid trajectory: " + "; ".join(validation["errors"][:5]))
    destination = Path(destination).expanduser().resolve()
    if _is_filesystem_root(destination):
        raise ValueError("Training export destination cannot be a filesystem root")
    destination.mkdir(parents=True, exist_ok=True)
    calls = reader.model_calls(include_incomplete=include_incomplete)
    events = reader.read_all(strict=False)
    evaluations_by_run: dict[str, dict[str, Any]] = {}
    evaluation_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "evaluation.completed":
            continue
        data = copy.deepcopy(event.get("data") or {})
        run_id = str(event.get("run_id") or data.get("run_id") or "")
        record = {"run_id": run_id or None, "sequence": event.get("sequence"), **data}
        evaluation_events.append(record)
        if run_id:
            evaluations_by_run[run_id] = record
    last_call_by_run: dict[str, str] = {}
    for call in calls:
        run_id = str((call.get("metadata") or {}).get("run_id") or "")
        if run_id:
            last_call_by_run[run_id] = str(call.get("model_call_id") or "")
    canonical_path = destination / "model_calls.jsonl"
    sharegpt_path = destination / "llamafactory_sharegpt.jsonl"
    verl_path = destination / "verl_rollouts.jsonl"
    episodes_path = destination / "egoagent_episodes.jsonl"
    exported = 0
    skipped = 0
    verl_rows: list[dict[str, Any]] = []
    with canonical_path.open("w", encoding="utf-8", newline="\n") as canonical, \
            sharegpt_path.open("w", encoding="utf-8", newline="\n") as sharegpt, \
            verl_path.open("w", encoding="utf-8", newline="\n") as verl:
        for call in calls:
            response = call.get("response") or {}
            if response.get("error") or (
                not include_incomplete
                and not str(response.get("content") or "").strip()
                and not response.get("tool_calls")
            ):
                skipped += 1
                continue
            canonical.write(json.dumps(call, ensure_ascii=False, separators=(",", ":")) + "\n")
            sharegpt.write(
                json.dumps(_sharegpt_sample(call, include_reasoning=include_reasoning), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            metadata = copy.deepcopy(call.get("metadata") or {})
            run_id = str(metadata.get("run_id") or "")
            evaluation = evaluations_by_run.get(run_id)
            is_terminal_call = bool(run_id and last_call_by_run.get(run_id) == call.get("model_call_id"))
            trusted_reward = None
            if evaluation is not None and is_terminal_call:
                try:
                    trusted_reward = float(evaluation.get("score"))
                except (TypeError, ValueError):
                    trusted_reward = None
            verl_sample = {
                "data_source": "egoagent_trajectory",
                "prompt": copy.deepcopy(call.get("messages") or []),
                "response": copy.deepcopy(response),
                "ability": metadata.get("purpose") or metadata.get("node_op") or "agent",
                "reward": trusted_reward,
                "reward_model": {
                    "style": (
                        str(evaluation.get("reward_style") or "task_bench_checker")
                        if trusted_reward is not None and evaluation is not None
                        else "external_verifier"
                    ),
                    "ground_truth": (
                        copy.deepcopy(evaluation.get("ground_truth", evaluation))
                        if trusted_reward is not None and evaluation is not None
                        else None
                    ),
                },
                "extra_info": {
                    **metadata,
                    "reward_assignment": "terminal_call" if trusted_reward is not None else "unassigned",
                },
            }
            verl.write(json.dumps(verl_sample, ensure_ascii=False, separators=(",", ":")) + "\n")
            verl_rows.append(copy.deepcopy(verl_sample))
            exported += 1
    episode = {
        "schema": "ego.trajectory-episode.v1",
        "trace_id": validation.get("trace_id"),
        "calls": calls,
        "evaluations": evaluation_events,
        "agents": sorted({str((call.get("metadata") or {}).get("agent")) for call in calls if (call.get("metadata") or {}).get("agent")}),
        "runs": sorted({str((call.get("metadata") or {}).get("run_id")) for call in calls if (call.get("metadata") or {}).get("run_id")}),
        "credit_assignment": "Only a deterministic checker score on the terminal call is exported as a direct verl reward; all other calls remain unlabelled.",
    }
    episodes_path.write_text(json.dumps(episode, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    dataset_info = {
        "egoagent_sft": {
            "file_name": sharegpt_path.name,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system", "tools": "tools"},
            "tags": {
                "role_tag": "from",
                "content_tag": "value",
                "user_tag": "human",
                "assistant_tag": "gpt",
                "observation_tag": "observation",
                "function_tag": "function_call",
            },
        }
    }
    dataset_info_path = destination / "dataset_info.json"
    dataset_info_path.write_text(json.dumps(dataset_info, ensure_ascii=False, indent=2), encoding="utf-8")
    verl_parquet_path: Optional[Path] = None
    verl_parquet_error: Optional[str] = None
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore

        verl_parquet_path = destination / "verl_rollouts.parquet"
        pq.write_table(pa.Table.from_pylist(verl_rows), verl_parquet_path)
    except ImportError:
        verl_parquet_error = (
            "pyarrow is not installed in the EgoAgent server environment; "
            "verl_rollouts.jsonl remains lossless and can be converted in the training environment"
        )
    except (OSError, TypeError, ValueError) as error:
        verl_parquet_path = None
        verl_parquet_error = f"could not write optional verl Parquet projection: {error}"
    manifest = {
        "schema": EXPORT_MANIFEST_SCHEMA,
        "created_at": time.time(),
        "source": str(Path(trajectory_path).resolve()),
        "source_sha256": hashlib.sha256(Path(trajectory_path).read_bytes()).hexdigest(),
        "trace_id": validation.get("trace_id"),
        "exported_model_calls": exported,
        "skipped_model_calls": skipped,
        "include_reasoning": bool(include_reasoning),
        "files": {
            "canonical": str(canonical_path),
            "llamafactory": str(sharegpt_path),
            "llamafactory_dataset_info": str(dataset_info_path),
            "verl": str(verl_path),
            "verl_parquet": str(verl_parquet_path) if verl_parquet_path else None,
            "egoagent_episodes": str(episodes_path),
        },
        "optional_projection_errors": {
            "verl_parquet": verl_parquet_error,
        },
        "notes": [
            "Each row is one exact Agent model call; multi-Agent calls are never merged into a synthetic speaker.",
            "verl rewards remain null unless an external checker or certificate supplies a trusted value.",
            "Task-level rewards are assigned only to the terminal call of the matching run; the episode file preserves all multi-Agent calls for custom credit assignment.",
            "Secrets are redacted before trajectory persistence.",
        ],
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def copy_native_trajectory(source: Path | str, destination: Path | str) -> Path:
    """Explicit utility for importing a completed legacy/native trace."""

    source = Path(source).resolve()
    destination = Path(destination).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if _is_filesystem_root(destination):
        raise ValueError("destination cannot be a filesystem root")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    shutil.copy2(source, target)
    return target
