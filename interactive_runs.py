"""Run-scoped state for the interactive DAG debugger.

The durable run queue owns background jobs.  This module owns the smaller,
live control plane used by Studio: input, approvals, pause/step directives and
the bounded UI projection.  Keeping those values on a run object prevents two
browser tabs or workspaces from sharing one process-global state dictionary.
"""

from __future__ import annotations

import contextvars
import copy
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional


def initial_execution_state() -> dict[str, Any]:
    return {
        "running": False,
        "status": "idle",
        "termination": None,
        "pending_approval": None,
        "approval_mode": "manual",
        "warnings": [],
        "waiting_for_input": False,
        "current_node": None,
        "workspace": "",
        "project_id": "",
        "session_name": "",
        "session_title": "",
        "session_id": "",
        # Identifies the UI/control surface that owns this live run.  A run
        # started from Chat must never be adopted by the independent Builder
        # merely because it is the newest run in the workspace.
        "surface": "unknown",
        "harness": "",
        "agents": {},
        "step_count": 0,
        "messages_count": 0,
        "debug_mode": "auto",
        "paused": False,
        "pause_requested": False,
        "pending_node": None,
        "pause_reason": None,
        "node_traces": [],
        "pipeline_run_id": "",
        "change_transaction_id": "",
        "_tick": 0,
    }


@dataclass
class InteractiveRun:
    run_id: str
    workspace: Path
    state: dict[str, Any] = field(default_factory=initial_execution_state)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    input_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    thread: Optional[threading.Thread] = field(default=None, repr=False)
    debug_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    approval_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    approval_requests: dict[str, dict] = field(default_factory=dict, repr=False)
    approval_answers: dict[str, dict] = field(default_factory=dict, repr=False)
    approval_closed: bool = False
    approval_mode_observer: Optional[Any] = field(default=None, repr=False)
    step_budget: int = 0
    node_directive: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.workspace = self.workspace.resolve()
        self.state["run_id"] = self.run_id
        self.state["workspace"] = str(self.workspace)

    def touch(self) -> None:
        self.touched_at = time.time()

    def _project_approvals(self):
        pending = next(iter(self.approval_requests.values()), None)
        was_approval_wait = self.state.get("status") == "waiting_approval" or bool(self.state.get("pending_approval"))
        self.state["pending_approval"] = copy.deepcopy(pending)
        if pending or was_approval_wait:
            self.state["waiting_for_input"] = bool(pending)
            if self.state.get("running"):
                self.state["status"] = "waiting_approval" if pending else "running"

    def request_approval(self, request):
        """Register a nonce, never replace an earlier unresolved request."""
        with self.approval_lock:
            if self.approval_closed or not self.state.get("running"):
                return
            nonce = str(request["approval_id"])
            if nonce in self.approval_requests or nonce in self.approval_answers:
                raise ValueError("Duplicate approval nonce")
            if self.state.get("approval_mode") == "auto" and request.get("auto_approvable"):
                self.approval_answers[nonce] = {"decision": "approved", "source": "automatic", "approval_id": nonce}
            else:
                self.approval_requests[nonce] = copy.deepcopy(request)
            self._project_approvals()

    def wait_for_approval(self, nonce, cancelled):
        """Separate from conversation input: a queued 'yes' cannot approve."""
        from pipeline_engine import PipelineCancelled
        try:
            while True:
                with self.approval_lock:
                    if self.approval_closed or not self.state.get("running") or cancelled():
                        raise PipelineCancelled("审批等待已取消；工具没有执行。")
                    answer = self.approval_answers.pop(nonce, None)
                    if answer is not None:
                        return answer
                    if nonce not in self.approval_requests:
                        raise PipelineCancelled("审批请求已失效；工具没有执行。")
                time.sleep(0.05)
        finally:
            with self.approval_lock:
                if self.approval_requests.pop(nonce, None) is not None:
                    self._project_approvals()
                self.approval_answers.pop(nonce, None)

    def close_approvals(self):
        with self.approval_lock:
            self.approval_closed = True
            self.approval_requests.clear()
            self.approval_answers.clear()
            self.state["pending_approval"] = None

    def snapshot(self, *, include_outputs: bool = False, include_traces: bool = True) -> dict[str, Any]:
        # Chat recovery needs messages, not every node's potentially huge I/O.
        # Filter before copying, so lightweight polling is lightweight on CPU too.
        source = self.state if include_traces else {k: v for k, v in self.state.items() if k != "node_traces"}
        payload = copy.deepcopy(source)
        payload["created_at"] = self.created_at
        payload["touched_at"] = self.touched_at
        if include_outputs:
            payload["outputs"] = copy.deepcopy(self.outputs)
        return payload


class InteractiveRunManager:
    def __init__(self, *, retention: int = 32) -> None:
        self.retention = max(2, int(retention))
        self._runs: dict[str, InteractiveRun] = {}
        self._lock = threading.RLock()
        self._current: contextvars.ContextVar[Optional[InteractiveRun]] = contextvars.ContextVar(
            "egoagent_interactive_run", default=None
        )

    def create(self, workspace: Path | str, *, run_id: Optional[str] = None) -> InteractiveRun:
        handle = InteractiveRun(
            run_id=str(run_id or f"interactive_{uuid.uuid4().hex}"),
            workspace=Path(workspace),
        )
        with self._lock:
            if handle.run_id in self._runs:
                raise ValueError(f"Interactive run already exists: {handle.run_id}")
            self._runs[handle.run_id] = handle
            self._prune_locked()
        return handle

    def get(self, run_id: object) -> Optional[InteractiveRun]:
        with self._lock:
            return self._runs.get(str(run_id or ""))

    def current(self) -> Optional[InteractiveRun]:
        return self._current.get()

    def latest(self, workspace: Path | str | None = None) -> Optional[InteractiveRun]:
        requested = Path(workspace).resolve() if workspace else None
        with self._lock:
            candidates = list(self._runs.values())
        if requested is not None:
            candidates = [item for item in candidates if item.workspace == requested]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.touched_at, item.created_at))

    def resolve(
        self,
        *,
        run_id: object = None,
        workspace: Path | str | None = None,
        required: bool = False,
    ) -> Optional[InteractiveRun]:
        handle = self.get(run_id) if run_id else self.current() or self.latest(workspace)
        if required and handle is None:
            raise KeyError("No interactive execution matches this request")
        return handle

    @contextmanager
    def bind(self, handle: InteractiveRun) -> Iterator[InteractiveRun]:
        token = self._current.set(handle)
        handle.touch()
        try:
            yield handle
        finally:
            self._current.reset(token)

    def list(self, workspace: Path | str | None = None, *, include_traces: bool = True) -> list[dict[str, Any]]:
        requested = Path(workspace).resolve() if workspace else None
        with self._lock:
            runs = list(self._runs.values())
        if requested is not None:
            runs = [item for item in runs if item.workspace == requested]
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return [item.snapshot(include_outputs=False, include_traces=include_traces) for item in runs]

    def remove(self, run_id: object) -> Optional[InteractiveRun]:
        """Forget a completed run (primarily useful for tests and retention jobs)."""

        with self._lock:
            handle = self._runs.get(str(run_id or ""))
            if handle is not None and handle.state.get("running"):
                raise RuntimeError(f"Cannot remove a running interactive execution: {handle.run_id}")
            return self._runs.pop(str(run_id or ""), None)

    def _prune_locked(self) -> None:
        completed = sorted(
            (item for item in self._runs.values() if not item.state.get("running")),
            key=lambda item: item.touched_at,
        )
        while len(self._runs) > self.retention and completed:
            stale = completed.pop(0)
            self._runs.pop(stale.run_id, None)


__all__ = ["InteractiveRun", "InteractiveRunManager", "initial_execution_state"]
