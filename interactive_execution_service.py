"""Transport-agnostic control plane for live Studio DAG executions.

HTTP and WebSocket handlers should translate requests and responses only.  The
state machine for pause/step/input/approval belongs here so every transport
uses the same nonce, locking and run-isolation rules.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from interactive_runs import InteractiveRun, InteractiveRunManager


class InteractiveExecutionError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


class InteractiveExecutionService:
    def __init__(
        self,
        manager: InteractiveRunManager,
        *,
        notify: Callable[[dict[str, Any]], None],
    ) -> None:
        self.manager = manager
        self.notify = notify

    def resolve(self, values: Optional[dict[str, Any]] = None, *, required: bool = False) -> Optional[InteractiveRun]:
        data = values or {}
        try:
            return self.manager.resolve(
                run_id=data.get("run_id") or data.get("execution_run_id"),
                workspace=data.get("workspace"),
                required=required,
            )
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            if required:
                raise InteractiveExecutionError("Interactive execution not found", 404) from error
            return None

    def state(self, values: Optional[dict[str, Any]] = None, *, include_outputs: bool = True,
              include_traces: bool = True) -> dict[str, Any]:
        handle = self.resolve(values, required=True)
        return handle.snapshot(include_outputs=include_outputs, include_traces=include_traces)

    def list(self, workspace: str | Path | None = None, *, include_traces: bool = True) -> list[dict[str, Any]]:
        return self.manager.list(workspace, include_traces=include_traces)

    def rename_session(self, session_name: str, title: str) -> None:
        """Keep the live run projection in sync with durable Session metadata."""

        target = str(session_name or "").strip()
        if not target:
            return
        for snapshot in self.manager.list():
            if str(snapshot.get("session_name") or "") != target:
                continue
            handle = self.manager.get(snapshot.get("run_id"))
            if handle is None:
                continue
            handle.state["session_title"] = str(title or "").strip()
            self._publish(handle)

    def dismiss(self, data: dict[str, Any]) -> dict[str, Any]:
        """Forget one completed live-run tab without deleting durable data."""

        handle = self.resolve(data, required=True)
        if handle.state.get("running"):
            raise InteractiveExecutionError("Stop the Session before removing it from the tab bar", 409)
        removed = self.manager.remove(handle.run_id)
        return {"ok": True, "run_id": handle.run_id, "dismissed": removed is not None}

    def start(
        self,
        *,
        workspace: str | Path,
        harness: str,
        agents: dict[str, str],
        debug_mode: str,
        mode: str,
        surface: str,
        mutation_targets: list[str],
        security: dict[str, Any],
        sandbox: dict[str, Any],
        worker_target: Callable[..., None],
        worker_args: tuple[Any, ...] | Callable[[InteractiveRun], tuple[Any, ...]],
        session_name: str = "",
        harness_version: str = "",
        approval_mode: str = "manual",
    ) -> InteractiveRun:
        handle = self.manager.create(Path(workspace))
        state = handle.state
        state.update({
            "running": True,
            "status": "running",
            "termination": None,
            "pending_approval": None,
            "approval_mode": "auto" if approval_mode == "auto" else "manual",
            "warnings": [],
            "waiting_for_input": False,
            "current_node": None,
            "workspace": str(handle.workspace),
            "harness": str(harness),
            "harness_version": str(harness_version or ""),
            "agents": dict(agents),
            "step_count": 0,
            "messages_count": 0,
            "debug_mode": "paused" if debug_mode in {"paused", "step"} else "auto",
            "paused": False,
            "pause_requested": debug_mode in {"paused", "step"},
            "pending_node": None,
            "pause_reason": None,
            "node_traces": [],
            "mode": mode,
            "surface": str(surface or "unknown"),
            "mutation_targets": list(mutation_targets),
            "security": dict(security),
            "sandbox": dict(sandbox),
            "session_name": str(session_name or ""),
        })
        self.notify(state)
        resolved_args = worker_args(handle) if callable(worker_args) else worker_args
        handle.thread = threading.Thread(target=worker_target, args=resolved_args, daemon=True)
        try:
            handle.thread.start()
        except BaseException:
            state.update({"running": False, "status": "error"})
            handle.touch()
            self.notify(state)
            self.manager.remove(handle.run_id)
            raise
        return handle

    def control(self, data: dict[str, Any]) -> dict[str, Any]:
        action = str(data.get("action", ""))
        handle = self.resolve(data, required=True)
        state = handle.state
        if not state.get("running"):
            raise InteractiveExecutionError("No execution running", 400)

        with handle.debug_condition:
            if action in {"resume", "auto"}:
                state.update({"debug_mode": "auto", "paused": False, "pause_requested": False})
                handle.step_budget = 0
            elif action == "pause":
                state.update({"debug_mode": "paused", "pause_requested": True})
            elif action in {"step", "continue"}:
                state.update({"debug_mode": "paused", "paused": False, "pause_requested": True})
                handle.step_budget = 1
            elif action in {"skip", "override_inputs", "retry_with_inputs"}:
                self._set_node_directive(handle, action, data)
            else:
                raise InteractiveExecutionError(
                    "action must be pause, step, continue, resume, auto, skip, override_inputs or retry_with_inputs"
                )
            handle.debug_condition.notify_all()
        self._publish(handle)
        return {"ok": True, **handle.snapshot()}

    @staticmethod
    def _set_node_directive(handle: InteractiveRun, action: str, data: dict[str, Any]) -> None:
        state = handle.state
        if action == "retry_with_inputs":
            if not state.get("paused") or state.get("pause_reason") != "error" or not state.get("pending_node"):
                raise InteractiveExecutionError("retry requires a debugger paused after a node error", 409)
            directive_action = "retry"
            field = "inputs"
        else:
            if not state.get("paused") or not state.get("pending_node"):
                message = "skip requires an execution paused before a node" if action == "skip" else "input override requires an execution paused before a node"
                raise InteractiveExecutionError(message, 409)
            directive_action = action
            field = "output" if action == "skip" else "inputs"
        expected = str(data.get("node_id") or state.get("pending_node"))
        if expected != state.get("pending_node"):
            raise InteractiveExecutionError("the requested node is not currently paused", 409)
        value = data.get(field, {}) if field == "output" else data.get(field)
        if not isinstance(value, dict):
            raise InteractiveExecutionError(f"{field} must be an object", 400)
        handle.node_directive = {"action": directive_action, "node_id": expected, field: value}
        state.update({"paused": False, "pause_requested": True})

    def stop(self, data: dict[str, Any]) -> dict[str, Any]:
        handle = self.resolve(data, required=True)
        state = handle.state
        state.update({
            "running": False,
            "status": "cancelled",
            "termination": {
                "kind": "cancelled",
                "message": "用户已停止本次 Agent 运行。",
                "at": time.time(),
            },
            "pending_approval": None,
            "waiting_for_input": False,
            "current_node": None,
            "paused": False,
            "pause_requested": False,
            "pending_node": None,
        })
        handle.close_approvals()
        while not handle.input_queue.empty():
            try:
                handle.input_queue.get_nowait()
            except queue.Empty:
                break
        handle.input_queue.put_nowait(None)
        with handle.debug_condition:
            handle.debug_condition.notify_all()
        self._publish(handle)
        if data.get("wait") and handle.thread is not None and handle.thread is not threading.current_thread():
            timeout = min(30.0, max(0.0, float(data.get("timeout", 10.0) or 10.0)))
            handle.thread.join(timeout=timeout)
            if handle.thread.is_alive():
                raise InteractiveExecutionError("Execution did not stop before the reconfiguration timeout", 409)
        return {"ok": True, "run_id": handle.run_id, "session_name": state.get("session_name", "")}

    def approval(self, data: dict[str, Any]) -> dict[str, Any]:
        handle = self.resolve(data, required=True)
        state = handle.state
        with handle.approval_lock:
            pending = state.get("pending_approval")
            if not state.get("running") or not isinstance(pending, dict):
                raise InteractiveExecutionError("No approval is pending", 409)
            approval_id = str(data.get("approval_id") or "")
            if approval_id != str(pending.get("approval_id") or ""):
                raise InteractiveExecutionError("Approval id is stale or belongs to another run", 409)
            decision = str(data.get("decision") or "rejected").strip().lower()
            if decision not in {"approved", "rejected"}:
                raise InteractiveExecutionError("decision must be approved or rejected", 400)
            answer = {"decision": decision, "answer": decision, "message": str(data.get("message") or "")}
            if "data" in data:
                answer["data"] = data["data"]
            # Nonce-addressed mailbox, not the general conversation queue.
            answer.update({"approval_id": approval_id, "source": "manual"})
            handle.approval_requests.pop(approval_id, None)
            handle.approval_answers[approval_id] = answer
            handle._project_approvals()
        self._publish(handle)
        return {"ok": True, "run_id": handle.run_id, "approval_id": approval_id, "decision": decision}

    def set_approval_mode(self, data: dict[str, Any]) -> dict[str, Any]:
        handle = self.resolve(data, required=True)
        mode = str(data.get("approval_mode", ""))
        if mode not in {"manual", "auto"}:
            raise InteractiveExecutionError("approval_mode must be manual or auto", 400)
        if mode == "auto" and data.get("confirmed") is not True:
            raise InteractiveExecutionError("Automatic tool approval requires explicit confirmation", 400)
        with handle.approval_lock:
            handle.state["approval_mode"] = mode
            if mode == "auto":
                for nonce, request in list(handle.approval_requests.items()):
                    if request.get("auto_approvable"):
                        handle.approval_answers[nonce] = {"decision": "approved", "source": "automatic", "approval_id": nonce}
                        del handle.approval_requests[nonce]
            handle._project_approvals()
            if callable(handle.approval_mode_observer):
                handle.approval_mode_observer(mode)
        self._publish(handle)
        return {"ok": True, "run_id": handle.run_id, "approval_mode": mode}

    def input(self, data: dict[str, Any]) -> dict[str, Any]:
        handle = self.resolve(data, required=True)
        state = handle.state
        if not state.get("running"):
            raise InteractiveExecutionError("No execution running", 400)
        if state.get("pending_approval"):
            raise InteractiveExecutionError(
                "A dangerous action is waiting for an explicit Allow or Reject decision", 409
            )
        state["waiting_for_input"] = False
        handle.input_queue.put(data.get("text", ""))
        self._publish(handle)
        return {"ok": True, "run_id": handle.run_id}

    def _publish(self, handle: InteractiveRun) -> None:
        handle.touch()
        self.notify(handle.state)


__all__ = ["InteractiveExecutionError", "InteractiveExecutionService"]
