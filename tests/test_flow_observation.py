import copy
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from flow_observation import FlowObservationStore, observation_store
from harness import Session
from pipeline_engine import PipelineRunner
from task_bench.engine import TaskBenchManager, TaskRun, _manifest


def graph(text="hello"):
    return {"name": "observation_fixture", "slots": {}, "prompts": {}, "pipeline": {
        "start": "answer", "max_steps": 3, "workspace_preview": False,
        "nodes": {"answer": {"id": "answer", "op": "输出", "value": text, "edges": [],
                              "editor_position": {"x": 50, "y": 120}}}}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("EGOAGENT_OBSERVATION_DIR", str(tmp_path / "recordings"))
    return observation_store()


def harness(tmp_path, source="chat_fixture"):
    return SimpleNamespace(config=graph(), workspace=tmp_path, dir=tmp_path, name="observation_fixture",
                           session=Session(workspace=tmp_path, save_dir=None), agents={}, parent=None,
                           observation_metadata={"entry_type": "chat", "source_run_id": source})


def test_pipeline_records_even_without_output_callback_or_done(store, tmp_path):
    ctx = PipelineRunner(harness(tmp_path), emit_done=False, auto_checkpoint=False).run()
    data = store.read("chat_fixture")
    assert ctx.observation_error is None
    assert data["runs"][0]["status"] == "completed"
    assert any(event["type"] == "node_output" for event in data["events"])
    assert any(event["type"] == "observation_finished" for event in data["events"])
    assert data["graphs"][data["events"][0]["graph_id"]]["pipeline"]["nodes"]["answer"]["editor_position"] == {"x": 50, "y": 120}


def test_subflow_events_record_once_in_parent_album(store, tmp_path):
    children = []
    def child(context, _node_id, _node):
        nested = harness(tmp_path, "not_a_new_root")
        nested.name = "child"
        runner = PipelineRunner(nested, on_output=context.emit, auto_checkpoint=False)
        children.append(runner.run())
    parent = PipelineRunner(harness(tmp_path), after_node=child, auto_checkpoint=False).run()
    frame = store.read("chat_fixture")
    assert len(frame["runs"]) == 2
    child_run = next(run for run in frame["runs"] if run["id"] == children[0].run_id)
    assert child_run["parent_id"] == parent.run_id
    assert child_run["metadata"]["parent_node_id"] == "answer"
    assert len([event for event in frame["events"] if event["type"] == "node_enter"]) == 2


def test_active_graph_and_library_edit_remain_distinct(store):
    initial = graph("initial")
    old = store.register("run", "root", None, initial, {"entry_type": "task"})
    proposed = graph("proposed")
    store.append("run", "harness_mutation", {"before": initial, "after": proposed})
    before_apply = store.read("root")
    mutation = before_apply["events"][-1]
    assert mutation["graph_id"] == old
    assert mutation["data"]["after_graph_id"] != old
    store.append("run", "node_enter", {"node_id": "answer"}, config=proposed)
    after_apply = store.read("root")
    assert after_apply["events"][-1]["graph_id"] != old
    assert after_apply["events"][-2]["data"]["reason"] == "active_graph_changed"
    assert after_apply["graphs"][old] == initial


def test_runner_captures_mutated_graph_at_next_node_boundary(store, tmp_path):
    flow = harness(tmp_path)
    nodes = flow.config["pipeline"]["nodes"]
    nodes["answer"].update({"continue": True, "edges": [{"condition": "default", "to": "finish"}]})
    nodes["finish"] = {"id": "finish", "op": "输出", "value": "old finish", "edges": []}
    def modify(context, node_id, _node):
        if node_id == "answer":
            context.graph["nodes"]["finish"]["value"] = "new finish"
    ctx = PipelineRunner(flow, after_node=modify, auto_checkpoint=False).run()
    page = store.read("chat_fixture")
    snapshots = [event for event in page["events"] if event["type"] == "graph_snapshot"]
    assert len(snapshots) == 2 and snapshots[-1]["data"]["reason"] == "active_graph_changed"
    assert page["graphs"][snapshots[0]["graph_id"]]["pipeline"]["nodes"]["finish"]["value"] == "old finish"
    assert page["graphs"][snapshots[1]["graph_id"]]["pipeline"]["nodes"]["finish"]["value"] == "new finish"
    assert ctx.stats.node_steps == 2


def test_recording_boundary_pagination_and_restart(store, tmp_path):
    store.register("run", "root", None, graph(), {})
    store.append("run", "node_enter", {"node_id": "answer"})
    rec = store.record("root", "start", "demo")
    assert store.record("root", "start")["id"] == rec["id"]
    for index in range(6):
        store.append("run", "token", {"text": str(index)})
    saved = store.record(action="stop", recording_id=rec["id"])
    store.append("run", "token", {"text": "after stop"})
    reopened = FlowObservationStore(tmp_path / "recordings")
    page = reopened.read("", limit=2, recording_id=rec["id"])
    assert page["has_more"] and len(page["events"]) == 2
    assert page["base_graphs"]
    events = page["events"]
    while page["has_more"]:
        page = reopened.read("", after=page["cursor"], limit=2, recording_id=rec["id"])
        events += page["events"]
    assert [event["data"]["text"] for event in events] == list("012345")
    assert events[-1]["sequence"] == saved["end_sequence"]
    assert reopened.record(action="rename", recording_id=rec["id"], title="renamed")["title"] == "renamed"
    assert len(reopened.recordings()) == 1


def test_sensitive_data_and_invalid_actions(store):
    store.register("run", "root", None, graph(), {"api_key": "private-test-key"})
    store.append("run", "model_request", {"api_key": "private-test-key", "input": "public fixture"})
    assert "private-test-key" not in json.dumps(store.read("root"))
    with pytest.raises(ValueError):
        store.record("../not-a-run", "start")
    with pytest.raises(ValueError):
        store.record("root", "delete-everything")
    assert store.read("' OR 1=1 --")["events"] == []


def test_finished_recording_does_not_leak_future_children_or_graphs(store):
    first = store.register("root_run", "root", None, graph("before"), {})
    recording = store.record("root", "save")
    store.append("root_run", "node_enter", {}, config=graph("after"))
    store.register("future_child", "root", "root_run", graph("child"), {})
    saved = store.read("", recording_id=recording["id"])
    assert [run["id"] for run in saved["runs"]] == ["root_run"]
    assert saved["runs"][0]["graph_id"] == first
    assert len(saved["events"]) == 1


def test_two_parallel_runs_keep_order_and_ownership(store):
    for run in ("left", "right"):
        store.register(run, run, None, graph(), {})
    def writer(run):
        for index in range(40):
            store.append(run, "token", {"text": f"{run}:{index}"})
    threads = [threading.Thread(target=writer, args=(run,)) for run in ("left", "right")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for run in ("left", "right"):
        events = store.read(run)["events"]
        assert len(events) == 41
        assert all(event["run_id"] == run for event in events)
        assert [event["sequence"] for event in events] == sorted({event["sequence"] for event in events})


def test_observer_failure_does_not_fail_or_repeat_execution(store, tmp_path):
    with patch("flow_observation.FlowObservationStore.append", side_effect=OSError("disk failure")):
        context = PipelineRunner(harness(tmp_path), auto_checkpoint=False).run()
    assert context.observation_error == "OSError"
    assert context.stats.node_steps == 1


def test_task_preparation_is_async_and_failure_is_visible(store, tmp_path):
    manager = TaskBenchManager(project_root=tmp_path)
    run = TaskRun(manager, {"id": "fixture", "evolution": {"allowed": False}}, {}, "auto")
    waiting = threading.Event()
    def prepare():
        waiting.wait(3)
        raise ValueError("fixture preparation failed")
    with patch.object(run, "prepare", side_effect=prepare):
        started = time.monotonic()
        run.start()
        assert time.monotonic() - started < 1
        assert run.state["status"] == "preparing" and run.state["running"]
        waiting.set()
        run.thread.join(3)
    assert run.state["status"] == "error" and not run.state["running"]
    assert "preparation failed" in run.state["error"]
    assert (run.run_dir / "summary.json").is_file()


def test_non_evolution_task_skips_global_manifest(store, tmp_path):
    (tmp_path / "harness").mkdir()
    (tmp_path / "identity").mkdir()
    manager = TaskBenchManager(project_root=tmp_path)
    run = TaskRun(manager, {"id": "fixture", "evolution": {"allowed": False}}, {}, "auto")
    with patch("task_bench.engine._manifest", side_effect=AssertionError("global scan")):
        run.prepare()
        assert not run._mutation_summary()["harness_modified"]


def test_manifest_does_not_traverse_immutable_versions(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    archived = tmp_path / ".versions" / "old"
    archived.mkdir(parents=True)
    (archived / "huge.json").write_text("old")
    assert set(_manifest(tmp_path)) == {"config.json"}


def test_manual_debug_wait_does_not_consume_task_timeout(tmp_path):
    manager = TaskBenchManager(project_root=tmp_path)
    run = TaskRun(manager, {"id": "fixture", "execution": {"timeout_seconds": 1}}, {}, "paused")
    run.state.update(running=True, status="running", paused=True, started_at=time.time() - 10)
    assert run._is_running()
    run._debug_paused_seconds = 10
    run.state["paused"] = False
    assert run._is_running()
    run._debug_paused_seconds = 0
    assert not run._is_running()
    assert run.state["status"] == "timeout"


def test_docker_build_file_is_absolute_and_failure_never_falls_back(tmp_path):
    import subprocess
    from task_bench.container_runtime import TaskContainer
    from task_bench.engine import TaskBenchError
    context = tmp_path / ".external" / "environment"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch")
    runtime = TaskContainer({"environment": {"network": "disabled"}}, tmp_path, tmp_path / "run")
    calls = []
    def docker(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")
    with patch.object(runtime, "available", return_value=(True, "mock")), patch.object(runtime, "_docker", side_effect=docker):
        runtime.start()
    build = calls[0]
    assert Path(build[build.index("--file") + 1]) == context / "Dockerfile"
    assert "--network" in calls[-1] and "none" in calls[-1]
    failing = TaskContainer({}, tmp_path, tmp_path / "failed")
    with patch.object(failing, "available", return_value=(False, "offline")), patch.object(failing, "_docker") as command:
        with pytest.raises(TaskBenchError, match="cannot start"):
            failing.start()
        command.assert_not_called()


def test_summary_listing_never_reloads_indexed_full_history(tmp_path):
    manager = TaskBenchManager(project_root=tmp_path)
    directory = manager.runs_dir / "old"
    directory.mkdir(parents=True)
    (directory / "run.json").write_text("not parsed: a huge legacy recording")
    manager._write_summary(directory, {"id": "old", "status": "passed", "created_at": 1})
    with patch.object(manager, "_recovery_checkpoint", side_effect=AssertionError("checkpoint scan")):
        assert manager.list_runs()[0]["id"] == "old"
