from pathlib import Path
from unittest.mock import patch

import pytest

from chat_progress import update_chat_progress
from workspace_revisions import tree_revision
from harness_editor.context_engine import plan_context


def test_tool_start_is_visible_before_tool_finishes_and_is_replayable():
    state = {}
    data = dict(run_id="child", tool_call_id="call-1", name="run_command", agent="coder",
                arguments={"command": "python -m unittest"})
    update_chat_progress(state, "tool_start", data)
    assert state["chat_progress"]["tools"][0]["status"] == "running"
    update_chat_progress(state, "tool_end", {**data, "status": "completed"})
    assert len(state["chat_progress"]["tools"]) == 1
    assert state["chat_progress"]["tools"][0]["status"] == "completed"
    update_chat_progress(state, "input_required", {})
    assert state["chat_progress"]["status"] == "completed"
    update_chat_progress(state, "node_enter", {"node_id": "input"})
    assert not state["chat_progress"]["tools"]


def test_reasoning_is_separate_bounded_and_keeps_agent_identity():
    state = {}
    for name in ["planner", "coder"]:
        update_chat_progress(state, "model_request", {"agent": name})
        update_chat_progress(state, "reasoning", {"agent": name, "text": name * 20000})
    thoughts = state["chat_progress"]["thinking"]
    assert [item["agent"] for item in thoughts] == ["planner", "coder"]
    assert all(len(item["text"]) == 16000 and item["truncated"] for item in thoughts)
    assert "outputs" not in state


def test_cancelled_tool_cannot_keep_spinning():
    state = {}
    update_chat_progress(state, "tool_start", {"name": "read_file"})
    update_chat_progress(state, "cancelled", {})
    assert state["chat_progress"]["tools"][0]["status"] == "interrupted"
    assert state["chat_progress"]["status"] == "cancelled"


def test_revision_prunes_ignored_tree_before_descending(tmp_path):
    (tmp_path / "source.py").write_text("hello")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "large.bin").write_bytes(b"a" * 100000)
    result = tree_revision(tmp_path, ignores={"node_modules"}, max_bytes=10)
    assert result["complete"]
    assert list(result["files"]) == ["source.py"]
    assert result["bytes_read"] == 5


def test_revision_budget_never_claims_complete(tmp_path):
    (tmp_path / "weights.bin").write_bytes(b"x" * 100)
    assert tree_revision(tmp_path, max_bytes=1)["complete"] is False
    assert tree_revision(tmp_path, max_seconds=0)["complete"] is False
    with pytest.raises(InterruptedError):
        tree_revision(tmp_path, cancelled=lambda: True)


def test_revision_cache_and_changed_file(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("first")
    cache = {}
    before = tree_revision(tmp_path, cache=cache)
    same = tree_revision(tmp_path, cache=cache)
    assert before["digest"] == same["digest"] and same["bytes_read"] == 0
    path.write_text("changed")
    assert tree_revision(tmp_path, cache=cache)["digest"] != before["digest"]


def test_chat_cold_index_keeps_explicit_selection_without_build(tmp_path):
    with patch("harness_editor.context_engine.build_index", side_effect=AssertionError("cold scan")):
        result = plan_context({"workspace": str(tmp_path), "cached_only": True,
                               "explicit": [{"content": "selected debug config", "kind": "selection"}]})
    assert "selected debug config" in result["prompt"]


def test_incomplete_checkpoint_fails_closed_on_resume():
    from pipeline_engine import PipelineRunner, PipelineRevisionConflict
    runner = PipelineRunner.__new__(PipelineRunner)
    runner.allow_revision_conflicts = False
    saved = {"workspace": {"digest": "same", "complete": False},
             "harness": {"digest": "same"}, "identities": {}}
    with patch.object(runner, "_revision_snapshot", return_value=saved):
        with pytest.raises(PipelineRevisionConflict):
            runner._validate_checkpoint_revisions({"revisions": saved})


def test_child_approval_uses_interactive_parent_not_headless_child():
    from types import SimpleNamespace
    from pipeline_engine import PipelineRunner
    parent = SimpleNamespace(parent=None, harness=SimpleNamespace(_non_interactive=False),
                             get_input=lambda: '{"decision":"approved"}')
    runner = PipelineRunner.__new__(PipelineRunner)
    runner.ctx = SimpleNamespace(parent=parent, harness=SimpleNamespace(_non_interactive=True),
                                 get_input=lambda: None, cancelled=lambda: False)
    assert runner._approval_answer() == '{"decision":"approved"}'
    parent.get_input = lambda: "rejected"
    assert runner._approval_answer() == "rejected"
    parent.harness._non_interactive = True
    parent.get_input = lambda: pytest.fail("headless root must never read interactive input")
    assert runner._approval_answer() == "rejected"
