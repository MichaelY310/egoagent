"""Durable lease-based coordination for long-running EgoAgent DAG runs.

The PipelineRunner remains the single interpreter. This module provides the
deployment layer above it: persistent queueing, atomic claims, renewable
leases, cancellation, retry after worker loss, checkpoint discovery and an
ordered event stream. SQLite makes the local/server implementation usable
without another service while preserving semantics that can later be mapped
to Postgres or a hosted queue.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
SECRET_MARKERS = ("api_key", "apikey", "authorization", "password", "secret", "token")


def _redact(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in SECRET_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): _redact(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decoded(value: Optional[str], fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


@dataclass(frozen=True)
class RunRecord:
    id: str
    status: str
    payload: dict[str, Any]
    result: Any
    error: Optional[str]
    priority: int
    attempts: int
    max_attempts: int
    lease_owner: Optional[str]
    lease_expires_at: Optional[float]
    heartbeat_at: Optional[float]
    cancel_requested: bool
    pause_requested: bool
    checkpoint_path: Optional[str]
    created_at: float
    updated_at: float
    available_at: float
    dedupe_key: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RunRecord":
        return cls(
            id=row["id"],
            status=row["status"],
            payload=_decoded(row["payload"], {}),
            result=_decoded(row["result"], None),
            error=row["error"],
            priority=int(row["priority"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            heartbeat_at=row["heartbeat_at"],
            cancel_requested=bool(row["cancel_requested"]),
            pause_requested=bool(row["pause_requested"]),
            checkpoint_path=row["checkpoint_path"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            available_at=float(row["available_at"]),
            dedupe_key=row["dedupe_key"],
        )

    def as_dict(self, include_payload: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "cancel_requested": self.cancel_requested,
            "pause_requested": self.pause_requested,
            "checkpoint_path": self.checkpoint_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "available_at": self.available_at,
            "dedupe_key": self.dedupe_key,
        }
        if include_payload:
            result["payload"] = _redact(self.payload)
        return result


class DurableRunQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    heartbeat_at REAL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    pause_requested INTEGER NOT NULL DEFAULT 0,
                    checkpoint_path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    available_at REAL NOT NULL,
                    dedupe_key TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_claim
                    ON runs(status, available_at, priority DESC, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_dedupe
                    ON runs(dedupe_key) WHERE dedupe_key IS NOT NULL;
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
            if "pause_requested" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0")
        finally:
            connection.close()

    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        run_id: Optional[str] = None,
        priority: int = 0,
        max_attempts: int = 3,
        available_at: Optional[float] = None,
        dedupe_key: Optional[str] = None,
    ) -> RunRecord:
        if not isinstance(payload, dict):
            raise TypeError("run payload must be an object")
        now = time.time()
        run_id = str(run_id or uuid.uuid4().hex)
        max_attempts = max(1, int(max_attempts))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if dedupe_key:
                existing = connection.execute(
                    "SELECT * FROM runs WHERE dedupe_key = ?", (str(dedupe_key),)
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return RunRecord.from_row(existing)
            connection.execute(
                """
                INSERT INTO runs(
                    id, status, payload, priority, max_attempts,
                    created_at, updated_at, available_at, dedupe_key
                ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _json(payload),
                    int(priority),
                    max_attempts,
                    now,
                    now,
                    float(available_at if available_at is not None else now),
                    str(dedupe_key) if dedupe_key else None,
                ),
            )
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            connection.commit()
            return RunRecord.from_row(row)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recover_expired(self, now: Optional[float] = None, connection: Optional[sqlite3.Connection] = None) -> int:
        owns_connection = connection is None
        connection = connection or self._connect()
        now = float(now if now is not None else time.time())
        try:
            if owns_connection:
                connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, attempts, max_attempts, cancel_requested, pause_requested FROM runs "
                "WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                (now,),
            ).fetchall()
            for row in rows:
                if row["cancel_requested"]:
                    status, error = "cancelled", "cancelled after worker lease expired"
                elif row["pause_requested"]:
                    status, error = "paused", "paused after worker lease expired"
                elif int(row["attempts"]) >= int(row["max_attempts"]):
                    status, error = "failed", "worker lease expired and retry budget was exhausted"
                elif self._checkpoint_phase_for_run(row["id"], connection) == "in_flight":
                    status, error = "interrupted", "worker stopped during a side-effecting node; inspection required"
                else:
                    status, error = "queued", "worker lease expired; run requeued"
                connection.execute(
                    """
                    UPDATE runs SET status = ?, error = ?, lease_owner = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        updated_at = ?, available_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (status, error, now, now, row["id"]),
                )
            if owns_connection:
                connection.commit()
            return len(rows)
        except BaseException:
            if owns_connection:
                connection.rollback()
            raise
        finally:
            if owns_connection:
                connection.close()

    @staticmethod
    def _checkpoint_phase(path: Optional[str]) -> str:
        if not path:
            return "unknown"
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return "unknown"
        return str(payload.get("phase", "completed"))

    def _checkpoint_phase_for_run(self, run_id: str, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT checkpoint_path FROM runs WHERE id = ?", (str(run_id),)).fetchone()
        return self._checkpoint_phase(row["checkpoint_path"] if row else None)

    def recover_startup(self) -> int:
        """Recover leases left by a previous local server process immediately."""
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, checkpoint_path, cancel_requested, pause_requested, attempts, max_attempts FROM runs WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                if row["cancel_requested"]:
                    status, error = "cancelled", "cancelled while the server was offline"
                elif row["pause_requested"]:
                    status, error = "paused", "pause completed while the server was offline"
                elif int(row["attempts"]) >= int(row["max_attempts"]):
                    status, error = "failed", "server restarted and retry budget was exhausted"
                elif self._checkpoint_phase(row["checkpoint_path"]) == "completed":
                    status, error = "queued", "server restarted; resuming from the last completed node"
                else:
                    status, error = "interrupted", "server restarted with an in-flight or unknown node; inspection required"
                connection.execute(
                    """
                    UPDATE runs SET status = ?, error = ?, lease_owner = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        updated_at = ?, available_at = ? WHERE id = ? AND status = 'running'
                    """,
                    (status, error, now, now, row["id"]),
                )
            connection.commit()
            return len(rows)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def checkpoint_preview(self, run_id: str) -> Optional[dict[str, Any]]:
        record = self.get(run_id)
        if record is None or not record.checkpoint_path:
            return None
        try:
            payload = json.loads(Path(record.checkpoint_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return {"path": record.checkpoint_path, "error": str(error)}
        return _redact({
            "path": record.checkpoint_path,
            "version": payload.get("version"),
            "phase": payload.get("phase", "completed"),
            "node": payload.get("node"),
            "next_node": payload.get("next_node"),
            "operation": payload.get("operation"),
            "created_at": payload.get("created_at"),
            "pending_approvals": payload.get("pending_approvals", {}),
            "artifacts": payload.get("artifacts", []),
            "completed_steps": payload.get("completed_steps", []),
            "revisions": payload.get("revisions", {}),
            "child_run_tree": payload.get("child_run_tree", {}),
        })

    def recover(self, run_id: str, action: str, *, confirm_in_doubt: bool = False, allow_revision_conflicts: bool = False) -> Optional[RunRecord]:
        action = str(action).lower()
        if action not in {"resume", "discard"}:
            raise ValueError("recovery action must be resume or discard")
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["status"] != "interrupted":
                raise ValueError(f"run is not interrupted: {row['status']}")
            if action == "discard":
                connection.execute(
                    "UPDATE runs SET status = 'cancelled', cancel_requested = 1, error = ?, updated_at = ? WHERE id = ?",
                    ("interrupted run discarded by user", now, str(run_id)),
                )
            else:
                phase = self._checkpoint_phase(row["checkpoint_path"])
                if phase != "completed" and not confirm_in_doubt:
                    raise ValueError("confirm_in_doubt=true is required to resume an in-flight node")
                payload = _decoded(row["payload"], {})
                payload["allow_inflight_resume"] = bool(confirm_in_doubt)
                payload["allow_revision_conflicts"] = bool(allow_revision_conflicts)
                connection.execute(
                    """
                    UPDATE runs SET status = 'queued', payload = ?, cancel_requested = 0,
                        error = NULL, available_at = ?, updated_at = ? WHERE id = ?
                    """,
                    (_json(payload), now, now, str(run_id)),
                )
            result = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            connection.commit()
            return RunRecord.from_row(result)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim(self, owner: str, lease_seconds: float = 30.0) -> Optional[RunRecord]:
        if not str(owner).strip():
            raise ValueError("lease owner is required")
        lease_seconds = max(0.1, float(lease_seconds))
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.recover_expired(now, connection=connection)
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE status = 'queued' AND cancel_requested = 0 AND available_at <= ?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                """
                UPDATE runs SET status = 'running', attempts = attempts + 1,
                    lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                    error = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (str(owner), now + lease_seconds, now, now, row["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            claimed = connection.execute("SELECT * FROM runs WHERE id = ?", (row["id"],)).fetchone()
            connection.commit()
            return RunRecord.from_row(claimed)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def heartbeat(self, run_id: str, owner: str, lease_seconds: float = 30.0) -> bool:
        now = time.time()
        connection = self._connect()
        try:
            updated = connection.execute(
                """
                UPDATE runs SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                    AND cancel_requested = 0 AND pause_requested = 0
                """,
                (now, now + max(0.1, float(lease_seconds)), now, str(run_id), str(owner)),
            )
            return updated.rowcount == 1
        finally:
            connection.close()

    def cancel(self, run_id: str) -> Optional[RunRecord]:
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["status"] in {"queued", "paused"}:
                connection.execute(
                    "UPDATE runs SET status = 'cancelled', cancel_requested = 1, pause_requested = 0, updated_at = ? WHERE id = ?",
                    (now, str(run_id)),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE runs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (now, str(run_id)),
                )
            result = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            connection.commit()
            return RunRecord.from_row(result)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pause(self, run_id: str) -> Optional[RunRecord]:
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["status"] == "queued":
                connection.execute(
                    "UPDATE runs SET status = 'paused', pause_requested = 0, updated_at = ? WHERE id = ?",
                    (now, str(run_id)),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE runs SET pause_requested = 1, updated_at = ? WHERE id = ?",
                    (now, str(run_id)),
                )
            result = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            connection.commit()
            return RunRecord.from_row(result)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def resume(self, run_id: str) -> Optional[RunRecord]:
        now = time.time()
        connection = self._connect()
        try:
            updated = connection.execute(
                "UPDATE runs SET status = 'queued', pause_requested = 0, cancel_requested = 0, "
                "error = NULL, available_at = ?, updated_at = ? WHERE id = ? AND status = 'paused'",
                (now, now, str(run_id)),
            )
            if updated.rowcount != 1:
                return self.get(run_id)
            return self.get(run_id)
        finally:
            connection.close()

    def acknowledge_pause(self, run_id: str, owner: str) -> bool:
        now = time.time()
        connection = self._connect()
        try:
            updated = connection.execute(
                """
                UPDATE runs SET status = 'paused', pause_requested = 0, lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ? AND pause_requested = 1
                """,
                (now, str(run_id), str(owner)),
            )
            return updated.rowcount == 1
        finally:
            connection.close()

    def is_pause_requested(self, run_id: str, owner: Optional[str] = None) -> bool:
        connection = self._connect()
        try:
            if owner is None:
                row = connection.execute(
                    "SELECT status, pause_requested FROM runs WHERE id = ?", (str(run_id),)
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT status, pause_requested FROM runs WHERE id = ? AND lease_owner = ?",
                    (str(run_id), str(owner)),
                ).fetchone()
            return bool(row and row["status"] == "running" and row["pause_requested"])
        finally:
            connection.close()

    def acknowledge_cancel(self, run_id: str, owner: str) -> bool:
        now = time.time()
        connection = self._connect()
        try:
            updated = connection.execute(
                """
                UPDATE runs SET status = 'cancelled', lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ? AND cancel_requested = 1
                """,
                (now, str(run_id), str(owner)),
            )
            return updated.rowcount == 1
        finally:
            connection.close()

    def is_cancel_requested(self, run_id: str, owner: Optional[str] = None) -> bool:
        connection = self._connect()
        try:
            if owner is None:
                row = connection.execute(
                    "SELECT status, cancel_requested FROM runs WHERE id = ?", (str(run_id),)
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT status, cancel_requested FROM runs WHERE id = ? AND lease_owner = ?",
                    (str(run_id), str(owner)),
                ).fetchone()
            return row is None or row["status"] != "running" or bool(row["cancel_requested"])
        finally:
            connection.close()

    def set_checkpoint(self, run_id: str, owner: str, checkpoint_path: str) -> bool:
        connection = self._connect()
        try:
            updated = connection.execute(
                """
                UPDATE runs SET checkpoint_path = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (str(checkpoint_path), time.time(), str(run_id), str(owner)),
            )
            return updated.rowcount == 1
        finally:
            connection.close()

    def complete(self, run_id: str, owner: str, result: Any) -> bool:
        now = time.time()
        connection = self._connect()
        try:
            updated = connection.execute(
                """
                UPDATE runs SET status = 'succeeded', result = ?, error = NULL,
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ? AND cancel_requested = 0
                """,
                (_json(result), now, str(run_id), str(owner)),
            )
            return updated.rowcount == 1
        finally:
            connection.close()

    def fail(self, run_id: str, owner: str, error: str, *, retryable: bool = True, delay: float = 0) -> bool:
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ? AND status = 'running' AND lease_owner = ?",
                (str(run_id), str(owner)),
            ).fetchone()
            if row is None:
                connection.commit()
                return False
            if row["cancel_requested"]:
                status = "cancelled"
            elif row["pause_requested"]:
                status = "paused"
            elif retryable and int(row["attempts"]) < int(row["max_attempts"]):
                status = "queued"
            else:
                status = "failed"
            connection.execute(
                """
                UPDATE runs SET status = ?, error = ?, lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    updated_at = ?, available_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (status, str(error)[:4000], now, now + max(0.0, float(delay)), str(run_id), str(owner)),
            )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_event(self, run_id: str, event: str, payload: Any) -> int:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            if exists is None:
                raise KeyError(f"unknown run: {run_id}")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM run_events WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            sequence = int(row["sequence"])
            connection.execute(
                "INSERT INTO run_events(run_id, sequence, event, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(run_id), sequence, str(event), _json(_redact(payload)), time.time()),
            )
            connection.commit()
            return sequence
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT sequence, event, payload, created_at FROM run_events
                WHERE run_id = ? AND sequence > ? ORDER BY sequence ASC LIMIT ?
                """,
                (str(run_id), max(0, int(after)), max(1, min(10000, int(limit)))),
            ).fetchall()
            return [
                {
                    "sequence": int(row["sequence"]),
                    "event": row["event"],
                    "payload": _decoded(row["payload"], {}),
                    "created_at": float(row["created_at"]),
                }
                for row in rows
            ]
        finally:
            connection.close()

    def get(self, run_id: str) -> Optional[RunRecord]:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (str(run_id),)).fetchone()
            return RunRecord.from_row(row) if row is not None else None
        finally:
            connection.close()

    def list(self, *, status: Optional[str] = None, limit: int = 100) -> list[RunRecord]:
        connection = self._connect()
        try:
            if status:
                rows = connection.execute(
                    "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (str(status), max(1, min(1000, int(limit)))),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(1000, int(limit))),),
                ).fetchall()
            return [RunRecord.from_row(row) for row in rows]
        finally:
            connection.close()


class DurableRunWorker:
    def __init__(
        self,
        queue: DurableRunQueue,
        execute: Callable[[RunRecord, Callable[[str, Any], None], Callable[[], bool]], Any],
        *,
        owner: Optional[str] = None,
        lease_seconds: float = 30.0,
        poll_seconds: float = 0.25,
    ):
        self.queue = queue
        self.execute = execute
        self.owner = str(owner or f"worker-{uuid.uuid4().hex[:12]}")
        self.lease_seconds = max(0.3, float(lease_seconds))
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "DurableRunWorker":
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self.run_forever, name=self.owner, daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, float(timeout)))

    def run_forever(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self.poll_seconds)

    def run_once(self) -> bool:
        record = self.queue.claim(self.owner, self.lease_seconds)
        if record is None:
            return False
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()

        def emit(event: str, payload: Any) -> None:
            self.queue.append_event(record.id, event, payload)
            if event == "checkpoint" and isinstance(payload, dict) and payload.get("path"):
                self.queue.set_checkpoint(record.id, self.owner, str(payload["path"]))

        def stopping() -> bool:
            return (
                self._stop.is_set()
                or lease_lost.is_set()
                or self.queue.is_cancel_requested(record.id, self.owner)
                or self.queue.is_pause_requested(record.id, self.owner)
            )

        def keep_alive() -> None:
            interval = max(0.1, self.lease_seconds / 3)
            while not heartbeat_stop.wait(interval):
                if not self.queue.heartbeat(record.id, self.owner, self.lease_seconds):
                    lease_lost.set()
                    return

        heartbeat = threading.Thread(target=keep_alive, name=f"{self.owner}-heartbeat", daemon=True)
        heartbeat.start()
        emit("worker_claimed", {"owner": self.owner, "attempt": record.attempts})
        try:
            result = self.execute(record, emit, stopping)
            if self.queue.is_cancel_requested(record.id, self.owner):
                self.queue.acknowledge_cancel(record.id, self.owner)
                emit("run_cancelled", {"owner": self.owner})
            elif self.queue.is_pause_requested(record.id, self.owner):
                self.queue.acknowledge_pause(record.id, self.owner)
                emit("run_paused", {"owner": self.owner})
            elif self.queue.complete(record.id, self.owner, result):
                emit("run_succeeded", {"owner": self.owner})
            elif self.queue.is_cancel_requested(record.id, self.owner):
                self.queue.acknowledge_cancel(record.id, self.owner)
                emit("run_cancelled", {"owner": self.owner})
        except Exception as error:
            if self.queue.is_cancel_requested(record.id, self.owner):
                self.queue.acknowledge_cancel(record.id, self.owner)
                emit("run_cancelled", {"owner": self.owner, "message": str(error)})
            elif self.queue.is_pause_requested(record.id, self.owner):
                self.queue.acknowledge_pause(record.id, self.owner)
                emit("run_paused", {"owner": self.owner, "message": str(error)})
            else:
                delay = min(60.0, 2 ** max(0, record.attempts - 1))
                retryable = bool(getattr(error, "retryable", True))
                self.queue.fail(record.id, self.owner, str(error), retryable=retryable, delay=delay)
                emit(
                    "run_failed",
                    {
                        "owner": self.owner,
                        "message": str(error),
                        "retryable": retryable,
                        "retry_delay": delay if retryable else 0,
                    },
                )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1.0)
        return True
