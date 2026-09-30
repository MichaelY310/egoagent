"""Regression for the WSL 9 x 300-second approval/retry failure.

Use deliberately tiny execution deadlines: waiting longer must not execute,
retry, erase tool results, or consume queued conversation messages.
"""
import threading
import time
from unittest.mock import Mock

import pytest

from interactive_execution_service import InteractiveExecutionService, InteractiveExecutionError
from interactive_runs import InteractiveRunManager
from pipeline_engine import PipelineRunner, PipelineCancelled, NodeTimeout, _call_with_timeout
from runtime_waits import human_wait, deadline_cancelled
from tests.test_pipeline_runtime import FakeHarness, FakeAgent
from permissions import RuntimePolicy


@pytest.fixture
def control(tmp_path):
    manager = InteractiveRunManager()
    handle = manager.create(tmp_path)
    handle.state.update(running=True, status="running")
    service = InteractiveExecutionService(manager, notify=lambda _: None)
    return handle, service


def request(handle, nonce, *, automatic=True):
    handle.request_approval({"approval_id": nonce, "auto_approvable": automatic, "tool": "run_command"})


def auto(handle, service):
    return service.set_approval_mode({"run_id": handle.run_id, "approval_mode": "auto", "confirmed": True})


def test_wait_is_excluded_from_nested_node_deadlines():
    def child():
        with human_wait():
            time.sleep(.3)
        return "done"
    assert _call_with_timeout(lambda: _call_with_timeout(child, .1), .15) == "done"


def test_real_work_still_times_out_and_late_worker_is_cancelled():
    completed = threading.Event()
    effects = []
    def work():
        time.sleep(.15)
        if not deadline_cancelled():
            effects.append("unsafe late write")
        completed.set()
    with pytest.raises(NodeTimeout):
        _call_with_timeout(work, .05)
    assert completed.wait(1)
    assert effects == []


def test_queued_yes_is_not_approval_and_parallel_children_do_not_steal_answers(control):
    handle, service = control
    handle.input_queue.put("yes")
    request(handle, "first")
    request(handle, "second")
    assert handle.state["pending_approval"]["approval_id"] == "first"
    answers = {}
    workers = [threading.Thread(target=lambda n=n: answers.update({n: handle.wait_for_approval(n, lambda: False)}))
               for n in ("first", "second")]
    for worker in workers:
        worker.start()
    service.approval({"run_id": handle.run_id, "approval_id": "first", "decision": "rejected"})
    assert handle.state["pending_approval"]["approval_id"] == "second"
    with pytest.raises(InteractiveExecutionError):
        service.approval({"run_id": handle.run_id, "approval_id": "first", "decision": "approved"})
    service.approval({"run_id": handle.run_id, "approval_id": "second", "decision": "approved"})
    for worker in workers:
        worker.join(1)
        assert not worker.is_alive()
    assert answers["first"]["decision"] == "rejected"
    assert answers["second"]["decision"] == "approved"
    assert handle.input_queue.get_nowait() == "yes"


def test_auto_switch_consumes_pending_tools_but_not_human_review(control):
    handle, service = control
    request(handle, "command")
    request(handle, "human", automatic=False)
    auto(handle, service)
    assert handle.wait_for_approval("command", lambda: False)["source"] == "automatic"
    assert handle.state["pending_approval"]["approval_id"] == "human"
    request(handle, "next-command")
    assert handle.wait_for_approval("next-command", lambda: False)["decision"] == "approved"
    service.set_approval_mode({"run_id": handle.run_id, "approval_mode": "manual"})
    request(handle, "manual-again")
    assert "manual-again" in handle.approval_requests


def test_auto_requires_confirmation_and_is_run_scoped(control, tmp_path):
    handle, service = control
    with pytest.raises(InteractiveExecutionError):
        service.set_approval_mode({"run_id": handle.run_id, "approval_mode": "auto"})
    other = service.manager.create(tmp_path)
    auto(handle, service)
    assert other.state["approval_mode"] == "manual"


def test_toggling_mode_does_not_turn_waiting_for_user_into_running(control):
    handle, service = control
    handle.state.update(waiting_for_input=True, status="waiting_input", current_node="input")
    auto(handle, service)
    assert handle.state["waiting_for_input"] is True
    assert handle.state["status"] == "waiting_input"


def test_stop_wakes_all_waiters_clears_cards_and_rejects_late_approval(control):
    handle, service = control
    request(handle, "one")
    request(handle, "two")
    cancelled = []
    def wait(nonce):
        try:
            handle.wait_for_approval(nonce, lambda: False)
        except PipelineCancelled:
            cancelled.append(nonce)
    threads = [threading.Thread(target=wait, args=(n,)) for n in ("one", "two")]
    for thread in threads:
        thread.start()
    service.stop({"run_id": handle.run_id})
    for thread in threads:
        thread.join(1)
    assert sorted(cancelled) == ["one", "two"]
    assert handle.state["pending_approval"] is None
    assert not handle.approval_requests and not handle.approval_answers
    with pytest.raises(InteractiveExecutionError):
        service.approval({"run_id": handle.run_id, "approval_id": "one", "decision": "approved"})


@pytest.mark.parametrize("decision", ["approved", "rejected", "auto", "stop"])
def test_actual_tool_node_waiting_beyond_timeout_does_not_retry(control, tmp_path, decision):
    handle, service = control
    agent = FakeAgent()
    agent.execute_tool_call = Mock(return_value="debug configuration contents")
    graph = {"start": "tools", "nodes": {
        "tools": {"op": "工具", "agent": "agent", "timeout_seconds": .2,
                  "inputs": {"tool_calls": [{"id": "call-one", "type": "function", "function": {
                      "name": "run_command", "arguments": '{"command":"ls .vscode"}'}}]},
                  "edges": [{"condition": "default", "to": "done"}]},
        "done": {"op": "结束"}}}
    harness = FakeHarness(tmp_path, graph, {"agent": agent})
    harness._non_interactive = False
    events = []
    ready = threading.Event()
    def output(kind, data):
        events.append((kind, data))
        if kind == "approval_required":
            handle.request_approval(data)
            ready.set()
    runner = PipelineRunner(harness, on_output=output, get_approval=handle.wait_for_approval,
                            permission_policy=RuntimePolicy.for_interactive_run(tmp_path, "agent"),
                            is_running=lambda: handle.state["running"], auto_checkpoint=False,
                            inject_workspace_preview=False)
    outcome = []
    def run():
        try:
            outcome.append(runner.run())
        except PipelineCancelled:
            outcome.append("cancelled")
    worker = threading.Thread(target=run)
    worker.start()
    assert ready.wait(3), [(kind, data.get("message")) for kind, data in events]
    time.sleep(.4)  # Twice the node timeout, without requiring a five-minute test.
    assert worker.is_alive()
    assert agent.execute_tool_call.call_count == 0
    assert not any(e in {"node_retry", "node_error"} for e, _ in events)
    if decision == "auto":
        auto(handle, service)
    elif decision == "stop":
        service.stop({"run_id": handle.run_id})
    else:
        service.approval({"run_id": handle.run_id, "approval_id": handle.state["pending_approval"]["approval_id"], "decision": decision})
    worker.join(3)
    assert not worker.is_alive()
    assert agent.execute_tool_call.call_count == (1 if decision in {"approved", "auto"} else 0)
    assert sum(e == "approval_required" for e, _ in events) == 1
    assert not any(e == "node_error" for e, _ in events)
    assert handle.state["pending_approval"] is None


def test_auto_never_overrides_chat_mode_process_denial(control, tmp_path):
    handle, service = control
    auto(handle, service)
    from permissions import RuntimePolicy
    policy = RuntimePolicy.for_interactive_run(tmp_path, "chat")
    decision = policy.evaluate_tool("run_command", {"command": "echo ok"})
    assert decision.decision.value == "deny"
    assert not handle.approval_answers
