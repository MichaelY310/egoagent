"""Durable workspace-local Agent registry and message bus.

The bus deliberately has no background thread.  DAG runs interact with it
through short SQLite transactions, so independently started workers can share
role registrations and reliably hand off typed artifacts without introducing
another always-on service.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Optional


class AgentBusError(RuntimeError):
    pass


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise AgentBusError(f"message bus value is not JSON serializable: {error}") from error


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _string_list(value: Any, *, name: str, allow_empty: bool = True) -> list[str]:
    if value is None:
        result: list[str] = []
    elif isinstance(value, str):
        result = [value]
    elif isinstance(value, (list, tuple, set)):
        result = [str(item) for item in value]
    else:
        raise AgentBusError(f"{name} must be a string or a list of strings")
    result = list(dict.fromkeys(item.strip() for item in result if item and item.strip()))
    if not allow_empty and not result:
        raise AgentBusError(f"{name} cannot be empty")
    return result


class AgentBus:
    """SQLite/WAL implementation with at-least-once delivery semantics."""

    def __init__(self, path: Path, *, max_payload_bytes: int = 1_000_000):
        self.path = Path(path)
        self.max_payload_bytes = max(1024, int(max_payload_bytes))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    identity_name TEXT NOT NULL DEFAULT '',
                    subscriptions_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    registered_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    max_attempts INTEGER NOT NULL DEFAULT 3
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    message_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    lease_owner TEXT,
                    lease_until REAL,
                    acknowledged_at REAL,
                    last_error TEXT,
                    PRIMARY KEY (message_id, recipient),
                    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS deliveries_claim_idx
                    ON deliveries(recipient, state, available_at, lease_until);
                CREATE INDEX IF NOT EXISTS messages_topic_idx
                    ON messages(topic, created_at);
                """
            )

    @staticmethod
    def _agent_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "identity": row["identity_name"],
            "subscriptions": _json_load(row["subscriptions_json"], []),
            "metadata": _json_load(row["metadata_json"], {}),
            "status": row["status"],
            "registered_at": row["registered_at"],
            "heartbeat_at": row["heartbeat_at"],
        }

    def register(
        self,
        agent_id: str,
        *,
        identity: str = "",
        subscriptions: Any = None,
        metadata: Any = None,
    ) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise AgentBusError("agent_id cannot be empty")
        patterns = _string_list(subscriptions, name="subscriptions")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise AgentBusError("agent metadata must be an object")
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO agents(
                    agent_id, identity_name, subscriptions_json, metadata_json,
                    status, registered_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    identity_name=excluded.identity_name,
                    subscriptions_json=excluded.subscriptions_json,
                    metadata_json=excluded.metadata_json,
                    status='active',
                    heartbeat_at=excluded.heartbeat_at
                """,
                (agent_id, str(identity or ""), _json_dump(patterns), _json_dump(metadata), now, now),
            )
            row = connection.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            connection.commit()
        return self._agent_from_row(row)

    def heartbeat(self, agent_id: str) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        now = time.time()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE agents SET heartbeat_at=? WHERE agent_id=? AND status='active'",
                (now, agent_id),
            )
            if cursor.rowcount != 1:
                raise AgentBusError(f"active agent is not registered: {agent_id}")
            row = connection.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        return self._agent_from_row(row)

    def unregister(self, agent_id: str) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE agents SET status='inactive', heartbeat_at=? WHERE agent_id=? AND status!='inactive'",
                (time.time(), str(agent_id or "").strip()),
            )
        return cursor.rowcount == 1

    def list_agents(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM agents" if include_inactive else "SELECT * FROM agents WHERE status='active'"
        query += " ORDER BY registered_at, agent_id"
        with closing(self._connect()) as connection:
            rows = connection.execute(query).fetchall()
        return [self._agent_from_row(row) for row in rows]

    @staticmethod
    def _subscribed(topic: str, subscriptions: Iterable[str]) -> bool:
        return any(fnmatch.fnmatchcase(topic, pattern) for pattern in subscriptions)

    def publish(
        self,
        *,
        topic: str,
        sender: str,
        payload: Any,
        recipients: Any = None,
        headers: Any = None,
        idempotency_key: Optional[str] = None,
        delay_seconds: float = 0.0,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        topic = str(topic or "").strip()
        sender = str(sender or "").strip()
        if not topic:
            raise AgentBusError("message topic cannot be empty")
        if not sender:
            raise AgentBusError("message sender cannot be empty")
        explicit_recipients = None if recipients is None else _string_list(recipients, name="recipients")
        if headers is None:
            headers = {}
        if not isinstance(headers, dict):
            raise AgentBusError("message headers must be an object")
        payload_json = _json_dump(payload)
        headers_json = _json_dump(headers)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise AgentBusError(f"message payload exceeds {self.max_payload_bytes} bytes")
        max_attempts = max(1, int(max_attempts))
        now = time.time()
        available_at = now + max(0.0, float(delay_seconds))
        key = str(idempotency_key).strip() if idempotency_key is not None else None
        key = key or None

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if key:
                existing = connection.execute(
                    "SELECT message_id FROM messages WHERE idempotency_key=?", (key,)
                ).fetchone()
                if existing is not None:
                    result = self._message_details(connection, existing["message_id"])
                    result["deduplicated"] = True
                    connection.commit()
                    return result

            if explicit_recipients is None:
                rows = connection.execute(
                    "SELECT agent_id, subscriptions_json FROM agents WHERE status='active'"
                ).fetchall()
                matched = [
                    row["agent_id"]
                    for row in rows
                    if self._subscribed(topic, _json_load(row["subscriptions_json"], []))
                ]
                target_recipients = sorted(set(matched))
            else:
                target_recipients = explicit_recipients

            message_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO messages(
                    message_id, topic, sender, payload_json, headers_json,
                    created_at, idempotency_key, max_attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, topic, sender, payload_json, headers_json, now, key, max_attempts),
            )
            connection.executemany(
                """
                INSERT INTO deliveries(message_id, recipient, state, attempt_count, available_at)
                VALUES (?, ?, 'pending', 0, ?)
                """,
                [(message_id, recipient, available_at) for recipient in target_recipients],
            )
            result = self._message_details(connection, message_id)
            result["deduplicated"] = False
            connection.commit()
        return result

    def _message_details(self, connection: sqlite3.Connection, message_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
        if row is None:
            raise AgentBusError(f"message does not exist: {message_id}")
        deliveries = connection.execute(
            """
            SELECT recipient, state, attempt_count, available_at, lease_owner,
                   lease_until, acknowledged_at, last_error
            FROM deliveries WHERE message_id=? ORDER BY recipient
            """,
            (message_id,),
        ).fetchall()
        return {
            "message_id": row["message_id"],
            "topic": row["topic"],
            "sender": row["sender"],
            "payload": _json_load(row["payload_json"], None),
            "headers": _json_load(row["headers_json"], {}),
            "created_at": row["created_at"],
            "idempotency_key": row["idempotency_key"],
            "max_attempts": row["max_attempts"],
            "recipients": [delivery["recipient"] for delivery in deliveries],
            "deliveries": [dict(delivery) for delivery in deliveries],
        }

    @staticmethod
    def _message_from_claim(
        row: sqlite3.Row,
        owner: str,
        lease_until: float,
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "topic": row["topic"],
            "sender": row["sender"],
            "recipient": row["recipient"],
            "payload": _json_load(row["payload_json"], None),
            "headers": _json_load(row["headers_json"], {}),
            "created_at": row["created_at"],
            "attempt": attempt,
            "receipt": {
                "message_id": row["message_id"],
                "recipient": row["recipient"],
                "lease_owner": owner,
                "lease_until": lease_until,
            },
        }

    def receive(
        self,
        *,
        agent_id: str,
        owner: str,
        topics: Any = None,
        limit: int = 1,
        lease_seconds: float = 30.0,
    ) -> list[dict[str, Any]]:
        agent_id = str(agent_id or "").strip()
        owner = str(owner or "").strip()
        if not agent_id or not owner:
            raise AgentBusError("message receive requires agent_id and lease owner")
        topic_patterns = _string_list(topics, name="topics") if topics is not None else []
        limit = max(1, min(int(limit), 1000))
        lease_seconds = max(0.01, float(lease_seconds))
        now = time.time()
        lease_until = now + lease_seconds

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            registered = connection.execute(
                "SELECT 1 FROM agents WHERE agent_id=? AND status='active'", (agent_id,)
            ).fetchone()
            if registered is None:
                raise AgentBusError(f"active agent is not registered: {agent_id}")
            connection.execute(
                """
                UPDATE deliveries
                SET state='dead', lease_owner=NULL, lease_until=NULL,
                    last_error=COALESCE(last_error, 'lease expired after max attempts')
                WHERE recipient=? AND state='leased' AND lease_until<=?
                  AND attempt_count >= (
                      SELECT max_attempts FROM messages WHERE messages.message_id=deliveries.message_id
                  )
                """,
                (agent_id, now),
            )
            rows = connection.execute(
                """
                SELECT m.*, d.recipient, d.state, d.attempt_count,
                       d.available_at, d.lease_until
                FROM deliveries d JOIN messages m ON m.message_id=d.message_id
                WHERE d.recipient=? AND d.available_at<=?
                  AND (
                    d.state='pending'
                    OR (d.state='leased' AND d.lease_until<=? AND d.attempt_count<m.max_attempts)
                    OR (d.state='leased' AND d.lease_owner=? AND d.lease_until>?)
                  )
                ORDER BY m.created_at, m.message_id
                """,
                (agent_id, now, now, owner, now),
            ).fetchall()
            selected = [
                row for row in rows
                if not topic_patterns or self._subscribed(row["topic"], topic_patterns)
            ][:limit]
            result = []
            for row in selected:
                same_owner_resume = row["state"] == "leased" and row["lease_until"] > now
                if same_owner_resume:
                    attempt = int(row["attempt_count"])
                    connection.execute(
                        """
                        UPDATE deliveries SET lease_until=?
                        WHERE message_id=? AND recipient=? AND state='leased' AND lease_owner=?
                        """,
                        (lease_until, row["message_id"], agent_id, owner),
                    )
                else:
                    attempt = int(row["attempt_count"]) + 1
                    connection.execute(
                        """
                        UPDATE deliveries
                        SET state='leased', attempt_count=attempt_count+1,
                            lease_owner=?, lease_until=?, last_error=NULL
                        WHERE message_id=? AND recipient=?
                        """,
                        (owner, lease_until, row["message_id"], agent_id),
                    )
                result.append(self._message_from_claim(row, owner, lease_until, attempt))
            connection.execute("UPDATE agents SET heartbeat_at=? WHERE agent_id=?", (now, agent_id))
            connection.commit()
        return result

    @staticmethod
    def _receipts(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict) and "receipt" in value:
            value = value["receipt"]
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            raise AgentBusError("receipts must be a receipt, message, or list")
        receipts = []
        for item in value:
            if isinstance(item, dict) and "receipt" in item:
                item = item["receipt"]
            if not isinstance(item, dict) or not item.get("message_id") or not item.get("recipient"):
                raise AgentBusError("each receipt requires message_id and recipient")
            receipts.append(item)
        return receipts

    def acknowledge(self, receipts: Any, *, owner: Optional[str] = None) -> dict[str, Any]:
        normalized = self._receipts(receipts)
        acknowledged = 0
        already_acknowledged = 0
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for receipt in normalized:
                receipt_owner = str(receipt.get("lease_owner") or owner or "")
                row = connection.execute(
                    "SELECT state, lease_owner FROM deliveries WHERE message_id=? AND recipient=?",
                    (str(receipt["message_id"]), str(receipt["recipient"])),
                ).fetchone()
                if row is None:
                    raise AgentBusError(f"delivery does not exist: {receipt['message_id']}/{receipt['recipient']}")
                if row["state"] == "acked":
                    already_acknowledged += 1
                    continue
                if row["state"] != "leased" or not receipt_owner or row["lease_owner"] != receipt_owner:
                    raise AgentBusError("delivery is not owned by this receipt")
                connection.execute(
                    """
                    UPDATE deliveries SET state='acked', acknowledged_at=?, lease_owner=NULL, lease_until=NULL
                    WHERE message_id=? AND recipient=?
                    """,
                    (time.time(), str(receipt["message_id"]), str(receipt["recipient"])),
                )
                acknowledged += 1
            connection.commit()
        return {
            "acknowledged": acknowledged,
            "already_acknowledged": already_acknowledged,
            "requested": len(normalized),
        }

    def reject(
        self,
        receipts: Any,
        *,
        owner: Optional[str] = None,
        error: str = "",
        delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        normalized = self._receipts(receipts)
        retried = 0
        dead = 0
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for receipt in normalized:
                receipt_owner = str(receipt.get("lease_owner") or owner or "")
                row = connection.execute(
                    """
                    SELECT d.state, d.lease_owner, d.attempt_count, m.max_attempts
                    FROM deliveries d JOIN messages m ON m.message_id=d.message_id
                    WHERE d.message_id=? AND d.recipient=?
                    """,
                    (str(receipt["message_id"]), str(receipt["recipient"])),
                ).fetchone()
                if row is None or row["state"] != "leased" or not receipt_owner or row["lease_owner"] != receipt_owner:
                    raise AgentBusError("delivery is not owned by this receipt")
                state = "dead" if int(row["attempt_count"]) >= int(row["max_attempts"]) else "pending"
                connection.execute(
                    """
                    UPDATE deliveries SET state=?, available_at=?, lease_owner=NULL,
                        lease_until=NULL, last_error=?
                    WHERE message_id=? AND recipient=?
                    """,
                    (
                        state,
                        now + max(0.0, float(delay_seconds)),
                        str(error or "")[:4000] or None,
                        str(receipt["message_id"]),
                        str(receipt["recipient"]),
                    ),
                )
                if state == "dead":
                    dead += 1
                else:
                    retried += 1
            connection.commit()
        return {"retried": retried, "dead": dead, "requested": len(normalized)}

    def list_messages(
        self,
        *,
        topic: Optional[str] = None,
        recipient: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if topic:
            clauses.append("m.topic=?")
            parameters.append(str(topic))
        if recipient:
            clauses.append("d.recipient=?")
            parameters.append(str(recipient))
        if state:
            clauses.append("d.state=?")
            parameters.append(str(state))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(int(limit), 1000)))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT m.message_id, m.topic, m.sender, m.payload_json, m.headers_json,
                       m.created_at, m.max_attempts, d.recipient, d.state,
                       d.attempt_count, d.available_at, d.lease_owner, d.lease_until,
                       d.acknowledged_at, d.last_error
                FROM messages m LEFT JOIN deliveries d ON d.message_id=m.message_id
                """ + where + " ORDER BY m.created_at DESC, m.message_id LIMIT ?",
                parameters,
            ).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if key not in {"payload_json", "headers_json"}},
                "payload": _json_load(row["payload_json"], None),
                "headers": _json_load(row["headers_json"], {}),
            }
            for row in rows
        ]
