import json
from pathlib import Path

from harness_editor import api_extensions
from task_bench.datasets import DatasetStore
from task_bench.engine import TaskBenchManager


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_dataset_and_governance_routes_use_the_same_workspace_services(tmp_path, monkeypatch):
    manager = TaskBenchManager(
        tmp_path,
        task_dir=tmp_path / "task_bench" / "tasks",
        runs_dir=tmp_path / ".egoagent" / "task_runs",
    )
    datasets = DatasetStore(tmp_path, task_dir=manager.task_dir)
    monkeypatch.setattr(api_extensions, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api_extensions, "_TASK_BENCH", manager)
    monkeypatch.setattr(api_extensions, "_TASK_DATASETS", datasets)

    preview, status = api_extensions.handle_api_request("POST", "/api/task-bench/datasets/preview", {
        "format": "jsonl",
        "content": json.dumps({"id": "case-1", "question": "answer alpha", "answer": "alpha"}),
        "mapping": {"id": "id", "prompt": "question", "expected": "answer"},
    })
    assert status == 200
    assert preview["row_count"] == 1

    created, status = api_extensions.handle_api_request("POST", "/api/task-bench/datasets", {
        "id": "api_fixture",
        "format": "jsonl",
        "content": json.dumps({"id": "case-1", "question": "answer alpha", "answer": "alpha"}),
        "mapping": {"id": "id", "prompt": "question", "expected": "answer"},
    })
    assert status == 201
    assert created["tasks"] == ["api_fixture__case-1"]
    tasks, status = api_extensions.handle_api_request("GET", "/api/task-bench/tasks")
    assert status == 200
    assert [item["id"] for item in tasks] == ["api_fixture__case-1"]

    _write(tmp_path / "harness" / "fixture" / "config.json", {
        "name": "fixture", "pipeline": {"nodes": {}, "permissions": {"defaults": {"network": "deny"}}},
    })
    _write(tmp_path / "identity" / "fixture" / "id.json", {"name": "fixture", "role": "tester"})
    _write(tmp_path / "identity" / "fixture" / "superego" / "config.json", {
        "tool_access": {"whitelist": ["read_file"], "blacklist": []},
        "allow_create_agent": False,
    })
    report, status = api_extensions.handle_api_request("POST", "/api/governance/inspect", {
        "harness": "fixture", "identity": "fixture", "mode": "evolve",
    })
    assert status == 200
    assert report["schema"] == "ego.governance-inspection.v1"
    process = next(row for row in report["matrix"] if row["capability"] == "process")
    assert process["effective"] == "deny"
