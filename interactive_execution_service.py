"""Transport-agnostic control plane for live Studio DAG executions.

HTTP and WebSocket handlers should translate requests and responses only.  The
state machine for pause/step/input/approval belongs here so every transport
uses the same nonce, locking and run-isolation rules.
"""

from __future__ import annotations

import json
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

    def state(self, values: Optional[dict[str, Any]] = None, *, include_outputs: bool = True) -> dict[str, Any]:
        handle = self.resolve(values, required=True)
        return handle.snapshot(include_outputs=include_outputs)

    def list(self, workspace: str | Path | None = None) -> list[dict[str, Any]]:
        return self.manager.list(workspace)

    def start(
        self,
        *,
        workspace: str | Path,
        harness: str,
        agents: dict[str, str],
        debug_mode: str,
        mode: str,
        mutation_targets: list[str],
        security: dict[str, Any],
        sandbox: dict[str, Any],
        worker_target: Callable[..., None],
        worker_args: tuple[Any, ...] | Callable[[InteractiveRun], tuple[Any, ...]],
    ) -> InteractiveRun:
        handle = self.manager.create(Path(workspace))
        state = handle.state
        state.update({
            "running": True,
            "status": "running",
            "termination": None,
            "pending_approval": None,
            "warnings": [],
            "waiting_for_input": False,
            "current_node": None,
            "workspace": str(handle.workspace),
            "harness": str(harness),
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
            "mutation_targets": list(mutation_targets),
            "security": dict(security),
            "sandbox": dict(sandbox),
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
        while not handle.input_queue.empty():
            try:
                handle.input_queue.get_nowait()
            except queue.Empty:
                break
        handle.input_queue.put_nowait(None)
        with handle.debug_condition:
            handle.debug_condition.notify_all()
        self._publish(handle)
        return {"ok": True, "run_id": handle.run_id}

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
            # Consume the nonce before enqueueing: double-clicks and replayed
            # HTTP requests can never authorize a second side effect.
            state.update({"pending_approval": None, "waiting_for_input": False, "status": "running"})
            handle.input_queue.put(json.dumps(answer, ensure_ascii=False))
        self._publish(handle)
        return {"ok": True, "run_id": handle.run_id, "approval_id": approval_id, "decision": decision}

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
