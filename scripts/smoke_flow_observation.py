"""Deterministic observer fixture. No model/API calls and no library mutations.

Creates a parent and child using the real PipelineRunner, then changes the
in-memory parent graph at a node boundary. This tests recording/replay, NOT
emergent self-evolution. Run from the repository: python scripts/smoke_flow_observation.py
"""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness import Session
from pipeline_engine import PipelineRunner
from flow_observation import observation_store


def main():
    fixture_dir = ROOT / ".runtime" / "observation-fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="replay-", dir=fixture_dir))
    source = "offline_observer_" + uuid.uuid4().hex[:12]
    def build(name, pipeline):
        return SimpleNamespace(name=name, dir=workspace, workspace=workspace, parent=None, agents={},
                               config={"name": name, "slots": {}, "prompts": {}, "pipeline": pipeline},
                               session=Session(workspace=workspace, save_dir=None),
                               observation_metadata={"entry_type": "offline-fixture", "source_run_id": source,
                                                     "note": "Scripted observer acceptance fixture, not model evolution"})
    pipeline = {"start": "prepare", "max_steps": 4, "workspace_preview": False, "nodes": {
        "prepare": {"id": "prepare", "op": "输出", "continue": True, "value": "Offline fixture: delegate then add verifier",
                    "edges": [{"condition": "default", "to": "finish"}], "editor_position": {"x": 0, "y": 60}},
        "finish": {"id": "finish", "op": "输出", "value": "finished", "edges": [], "editor_position": {"x": 620, "y": 60}},
    }}
    parent = build("offline_observer_parent", pipeline)
    changed = False
    def boundary(context, node_id, _node):
        nonlocal changed
        if node_id != "prepare" or changed:
            return
        changed = True
        child = build("offline_observer_child", {"start": "answer", "max_steps": 2, "nodes": {
            "answer": {"id": "answer", "op": "输出", "value": "child result-only answer", "edges": []}}})
        PipelineRunner(child, on_output=context.emit, auto_checkpoint=False).run()
        before = copy.deepcopy(parent.config)
        context.graph["nodes"]["finish"]["continue"] = True
        context.graph["nodes"]["finish"]["edges"] = [{"condition": "default", "to": "verify"}]
        context.graph["nodes"]["verify"] = {"id": "verify", "op": "输出", "value": "verified",
                                              "edges": [], "editor_position": {"x": 1240, "y": 60}}
        context.emit("harness_mutation", {"before": before, "after": {**parent.config, "pipeline": context.graph},
                                           "fixture": True, "note": "Explicit scripted edit, no self-evolution claim"})
        # Observe the added node at a subsequent real node boundary. We do not
        # edit any library config or pretend the model decided to change it.
    context = PipelineRunner(parent, after_node=boundary, auto_checkpoint=False).run()
    store = observation_store()
    page = store.read(source)
    assert context.observation_error is None
    assert len(page["runs"]) == 2
    assert any(event["type"] == "node_enter" and event["data"].get("node_id") == "verify" for event in page["events"])
    assert any(event["type"] == "graph_snapshot" and event["data"].get("reason") == "active_graph_changed" for event in page["events"])
    saved = store.record(source, "save", "离线验收 · 父子 Flow 与生效结构回放（脚本夹具）")
    print(json.dumps({"root_id": source, "recording_id": saved["id"], "runs": len(page["runs"]),
                      "graphs": len(page["graphs"]), "events": len(page["events"]),
                      "recording_error": context.observation_error}, ensure_ascii=False))


if __name__ == "__main__":
    main()
