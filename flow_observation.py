"""Passive, durable Flow observability, shared by every PipelineRunner entry.

This is a UI event index, not a second execution engine or training trajectory.
Recordings are immutable event ranges: replay never calls a tool or a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from trajectory import redact_sensitive_value


def _json(value: Any) -> str:
    safe, _ = redact_sensitive_value(value)
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)


class FlowObservationStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "observations.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS graphs (id TEXT PRIMARY KEY, config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, root_id TEXT NOT NULL, parent_id TEXT,
                created REAL NOT NULL, updated REAL NOT NULL, status TEXT NOT NULL,
                graph_id TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS runs_root ON runs(root_id, created);
            CREATE INDEX IF NOT EXISTS runs_updated ON runs(updated);
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, root_id TEXT NOT NULL,
                run_id TEXT NOT NULL, time REAL NOT NULL, type TEXT NOT NULL,
                graph_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_root ON events(root_id, sequence);
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id, sequence);
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY, root_id TEXT NOT NULL, title TEXT NOT NULL,
                created REAL NOT NULL, start_sequence INTEGER NOT NULL,
                end_sequence INTEGER, base_sequence INTEGER NOT NULL);
        """)
        self.db.commit()

    def _graph(self, config: dict) -> str:
        encoded = _json(config)
        key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO graphs VALUES (?, ?)", (key, encoded))
        return key

    def register(self, run_id: str, root_id: str, parent_id: str | None, config: dict, metadata: dict) -> str:
        with self.lock, self.db:
            graph_id = self._graph(config)
            now = time.time()
            self.db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (run_id, root_id, parent_id, now, now, "running", graph_id, _json(metadata)))
            self._append(root_id, run_id, "graph_snapshot", {"reason": "execution_started"}, graph_id)
            return graph_id

    def _append(self, root: str, run: str, event: str, data: dict, graph: str) -> int:
        return self.db.execute("INSERT INTO events(root_id,run_id,time,type,graph_id,data) VALUES(?,?,?,?,?,?)",
                               (root, run, time.time(), event, graph, _json(data))).lastrowid

    def append(self, run_id: str, event: str, data: dict, *, config: dict | None = None) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown observed run")
            graph_id = self._graph(config) if config is not None else row["graph_id"]
            if graph_id != row["graph_id"]:
                self._append(row["root_id"], run_id, "graph_snapshot", {"reason": "active_graph_changed"}, graph_id)
            # Keep proposal/library edits separate from the executing graph.
            # Their exact before/after snapshots are retained, without implying
            # that the running interpreter has adopted them.
            data = dict(data)
            if event == "harness_mutation":
                for side in ("before", "after"):
                    if isinstance(data.get(side), dict):
                        data[side + "_graph_id"] = self._graph(data.pop(side))
                data["application"] = "library_edit; active graph is recorded separately"
            status = str(data.get("status", "completed")) if event == "observation_finished" else row["status"]
            if event in {"debug_paused", "debug_resumed"}:
                status = "paused" if event == "debug_paused" else "running"
            elif event == "input_required":
                status = "waiting_input"
            elif event == "approval_required":
                status = "waiting_approval"
            elif event == "node_enter":
                status = "running"
            self._append(row["root_id"], run_id, event, data, graph_id)
            self.db.execute("UPDATE runs SET updated=?,graph_id=?,status=? WHERE id=?",
                            (time.time(), graph_id, status, run_id))

    @staticmethod
    def _run(row) -> dict:
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"])
        return result

    def list_runs(self, limit: int = 100) -> list[dict]:
        with self.lock:
            rows = self.db.execute("""SELECT root_id, MAX(updated) updated, MIN(created) created,
                COUNT(*) run_count, SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) active
                FROM runs GROUP BY root_id ORDER BY updated DESC LIMIT ?""", (max(1, min(limit, 200)),)).fetchall()
            result = []
            for row in rows:
                latest = self.db.execute("SELECT * FROM runs WHERE root_id=? AND parent_id IS NULL ORDER BY created DESC LIMIT 1",
                                         (row["root_id"],)).fetchone()
                latest = latest or self.db.execute("SELECT * FROM runs WHERE root_id=? LIMIT 1", (row["root_id"],)).fetchone()
                item = {**self._run(latest), **dict(row)}
                item["status"] = "running" if row["active"] else latest["status"]
                result.append(item)
            return result

    def read(self, root_id: str, after: int = 0, limit: int = 500, recording_id: str = "") -> dict:
        with self.lock:
            recording = None
            end = None
            if recording_id:
                recording = self._recording(recording_id)
                root_id = recording["root_id"]
                after = max(int(after), recording["start_sequence"] - 1)
                end = recording["end_sequence"]
            runs = [self._run(row) for row in self.db.execute("SELECT * FROM runs WHERE root_id=? ORDER BY created", (root_id,))]
            if end is not None:
                bounded_runs = []
                for run in runs:
                    boundary = self.db.execute("SELECT * FROM events WHERE run_id=? AND sequence<=? ORDER BY sequence DESC LIMIT 1", (run["id"], end)).fetchone()
                    if boundary is None:
                        continue
                    run["graph_id"] = boundary["graph_id"]
                    finished = self.db.execute("SELECT data FROM events WHERE run_id=? AND type='observation_finished' AND sequence<=? ORDER BY sequence DESC LIMIT 1", (run["id"], end)).fetchone()
                    run["status"] = json.loads(finished[0])["status"] if finished else "recording_boundary"
                    bounded_runs.append(run)
                runs = bounded_runs
            if not runs:
                return {"root_id": root_id, "runs": [], "events": [], "graphs": {}, "cursor": after, "has_more": False}
            rows = self.db.execute("""SELECT * FROM events WHERE root_id=? AND sequence>? AND (? IS NULL OR sequence<=?)
                ORDER BY sequence LIMIT ?""", (root_id, max(0, int(after)), end, end, max(1, min(int(limit), 1000)) + 1)).fetchall()
            has_more = len(rows) > max(1, min(int(limit), 1000))
            rows = rows[:max(1, min(int(limit), 1000))]
            events = [{**dict(row), "data": json.loads(row["data"])} for row in rows]
            graph_ids = {run["graph_id"] for run in runs} | {row["graph_id"] for row in rows}
            for event in events:
                for key in ("before_graph_id", "after_graph_id"):
                    if event["data"].get(key):
                        graph_ids.add(event["data"][key])
            # A mid-run recording must display the graph at its start, not the
            # graph that happens to be latest when the album is opened.
            bases = []
            if recording:
                for run in runs:
                    base = self.db.execute("SELECT * FROM events WHERE run_id=? AND sequence<=? ORDER BY sequence DESC LIMIT 1",
                                           (run["id"], recording["base_sequence"])).fetchone()
                    if base:
                        graph_ids.add(base["graph_id"])
                        bases.append({"run_id": run["id"], "graph_id": base["graph_id"]})
            graphs = {}
            for key in graph_ids:
                row = self.db.execute("SELECT config FROM graphs WHERE id=?", (key,)).fetchone()
                if row:
                    graphs[key] = json.loads(row[0])
            return {"root_id": root_id, "runs": runs, "events": events, "graphs": graphs,
                    "cursor": events[-1]["sequence"] if events else after, "has_more": has_more,
                    "recording": recording, "base_graphs": bases}

    def _recording(self, recording_id: str) -> dict:
        row = self.db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
        if row is None:
            raise ValueError("Recording not found")
        return dict(row)

    def recordings(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM recordings ORDER BY created DESC LIMIT 200")]

    def record(self, root_id: str = "", action: str = "start", title: str = "", recording_id: str = "") -> dict:
        with self.lock, self.db:
            if action in {"stop", "rename"}:
                record = self._recording(recording_id)
                if action == "stop" and record["end_sequence"] is None:
                    last = self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE root_id=?", (record["root_id"],)).fetchone()[0]
                    self.db.execute("UPDATE recordings SET end_sequence=? WHERE id=?", (last, recording_id))
                elif action == "rename":
                    if not title.strip():
                        raise ValueError("Title cannot be empty")
                    self.db.execute("UPDATE recordings SET title=? WHERE id=?", (title.strip()[:200], recording_id))
                return self._recording(recording_id)
            if action not in {"start", "save"}:
                raise ValueError("Unknown recording action")
            if not self.db.execute("SELECT 1 FROM runs WHERE root_id=?", (root_id,)).fetchone():
                raise ValueError("Run has not reached the Flow interpreter yet")
            last = self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE root_id=?", (root_id,)).fetchone()[0]
            if action == "start":
                existing = self.db.execute("SELECT * FROM recordings WHERE root_id=? AND end_sequence IS NULL", (root_id,)).fetchone()
                if existing:
                    return dict(existing)
            key = uuid.uuid4().hex
            self.db.execute("INSERT INTO recordings VALUES(?,?,?,?,?,?,?)", (
                key, root_id, title.strip()[:200] or f"Flow · {root_id[-8:]}", time.time(),
                last + 1 if action == "start" else 0, None if action == "start" else last,
                last if action == "start" else 0))
            return self._recording(key)


_stores: dict[str, FlowObservationStore] = {}
_stores_lock = threading.Lock()


def observation_store() -> FlowObservationStore:
    directory = Path(os.environ.get("EGOAGENT_OBSERVATION_DIR") or Path(__file__).resolve().parent / ".egoagent" / "observations").resolve()
    with _stores_lock:
        if str(directory) not in _stores:
            _stores[str(directory)] = FlowObservationStore(directory)
        return _stores[str(directory)]


class FlowObserver:
    """Adapter owned by RunContext. Never receives permission to execute tools."""
    def __init__(self, context):
        self.context = context
        self.store = observation_store()
        harness = context.harness
        metadata = dict(getattr(harness, "observation_metadata", {}) or {})
        parent_observer = getattr(context.parent, "flow_observer", None)
        self.root_id = parent_observer.root_id if parent_observer else str(metadata.get("source_run_id") or context.run_id)
        identity = lambda agent: Path(getattr(getattr(agent, "identity", None), "identity_path", "")).name
        metadata.update(harness=getattr(harness, "name", None), workspace=str(context.workspace),
                        session_id=getattr(context.session, "session_id", None),
                        slots={str(slot): identity(agent) for slot, agent in getattr(harness, "agents", {}).items()},
                        parent_node_id=getattr(context.parent, "current_node", None),
                        trajectory_path=str(getattr(getattr(context.session, "trajectory", None), "native_path", "") or ""),
                        owner_pid=os.getpid())
        metadata.setdefault("entry_type", "subflow" if context.parent else "python/cli")
        self.store.register(context.run_id, self.root_id, context.parent_run_id, self.config(), metadata)

    def config(self):
        harness = self.context.harness
        config = dict(getattr(harness, "config", {}) or {})
        config.update(name=getattr(harness, "name", "Flow"), pipeline=self.context.graph)
        return self.context.secret_view.redact_value(config)

    def emit(self, event: str, data: dict):
        # Only check the active graph at node boundaries, not for every token.
        config = self.config() if event in {"run_started", "node_enter"} else None
        self.store.append(self.context.run_id, event, data, config=config)
