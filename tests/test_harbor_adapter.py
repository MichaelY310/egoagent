import json
import tempfile
import time
import unittest
from pathlib import Path

from task_bench.container_runtime import TaskContainer
from task_bench.engine import TaskBenchManager
from task_bench.harbor_adapter import (
    detect_task_format,
    export_harbor_task,
    import_harbor_task,
    import_terminal_bench_task,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, value: dict) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2))


class HarborAdapterTests(unittest.TestCase):
    def make_harbor(self, root: Path, *, steps: bool = False) -> Path:
        task = root / "harbor_task"
        write(task / "instruction.md", "Create answer.txt with the final answer.\n")
        write(task / "environment" / "Dockerfile", "FROM ubuntu:24.04\nWORKDIR /app\n")
        write(task / "tests" / "test.sh", "#!/bin/sh\nmkdir -p /logs/verifier\necho 1 > /logs/verifier/reward.txt\n")
        metadata = '''schema_version = "1.4"
[task]
name = "imported_harbor"
version = "1.2.3"
description = "Imported Harbor fixture"
keywords = ["offline", "fixture"]
authors = [{name = "Researcher", email = "r@example.test"}]
[agent]
timeout_sec = 60
[verifier]
timeout_sec = 30
[environment]
allow_internet = false
workdir = "/app"
'''
        if steps:
            metadata += '''
[[steps]]
name = "discover"
description = "Discover"
min_reward = 0.5
[[steps]]
name = "finish"
description = "Finish"
min_reward = 1.0
resume_trajectory = true
'''
            for name in ("discover", "finish"):
                write(task / "steps" / name / "instruction.md", f"Complete {name}.\n")
                write(task / "steps" / name / "tests" / "test.sh", "#!/bin/sh\nmkdir -p /logs/verifier\necho 1 > /logs/verifier/reward.txt\n")
            write(task / "steps" / "discover" / "workdir" / "seed.txt", "seed")
        write(task / "task.toml", metadata)
        return task

    def test_harbor_import_is_self_contained_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_harbor(root)
            self.assertEqual(detect_task_format(source), "harbor")
            spec = import_harbor_task(source)
            self.assertEqual(spec["id"], "imported_harbor")
            self.assertEqual(spec["environment"]["backend"], "container")
            self.assertIn(".external/environment/Dockerfile", spec["workspace"]["files"])
            self.assertNotIn("source", spec)
            exported = export_harbor_task(spec, root / "exported")
            self.assertTrue((exported / "task.toml").is_file())
            self.assertTrue((exported / "tests" / "test.sh").is_file())
            round_trip = import_harbor_task(exported)
            self.assertEqual(round_trip["id"], spec["id"])
            self.assertEqual(round_trip["prompt"], spec["prompt"])

    def test_multistep_harbor_import_preserves_step_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = import_harbor_task(self.make_harbor(Path(directory), steps=True))
            self.assertEqual([step["id"] for step in spec["steps"]], ["discover", "finish"])
            self.assertFalse(spec["steps"][0]["resume_trajectory"])
            self.assertTrue(spec["steps"][1]["resume_trajectory"])
            self.assertEqual(spec["steps"][0]["evaluation"]["checks"][0]["minimum_reward"], 0.5)

    def test_legacy_terminal_bench_import(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "legacy"
            write(task / "task.yaml", "name: legacy_task\ninstruction: Fix the fixture\nmax_agent_timeout_sec: 42\n")
            write(task / "Dockerfile", "FROM ubuntu:24.04\nWORKDIR /app\n")
            write(task / "run-tests.sh", "#!/bin/sh\nexit 0\n")
            spec = import_terminal_bench_task(task)
            self.assertEqual(detect_task_format(task), "terminal-bench")
            self.assertEqual(spec["execution"]["timeout_seconds"], 42)
            self.assertTrue(spec["evaluation"]["checks"][0]["legacy_terminal_bench"])

    def test_import_rejects_symlinks_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = self.make_harbor(root)
            outside = root / "outside.txt"
            write(outside, "secret")
            try:
                (task / "environment" / "escape").symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(Exception, "Symlinks"):
                import_harbor_task(task)

    def test_verifier_uses_numeric_reward(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            write(workspace / "tests" / "test.sh", "#!/bin/sh\n")
            runtime = TaskContainer({"environment": {"container": {}}}, workspace, run_dir)
            runtime.started = True
            runtime.execute = lambda *args, **kwargs: {"exit_code": 0, "stdout": "ok", "stderr": ""}
            write(runtime.logs_dir / "verifier" / "reward.txt", "0.75")
            passed, _, details = runtime.run_verifier({
                "script": "tests/test.sh", "minimum_reward": 0.5, "timeout_seconds": 2,
            })
            self.assertTrue(passed)
            self.assertEqual(details["reward"], 0.75)

    def test_multistep_engine_reuses_workspace_and_records_each_step(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            write_json(project / "identity" / "fixture" / "id.json", {
                "name": "fixture", "role": "offline", "llm": {"type": "dummy_llm", "mode": "scripted", "script": []},
            })
            write_json(project / "harness" / "writer" / "config.json", {
                "name": "writer", "slots": {}, "prompts": {},
                "pipeline": {"start": "write", "max_steps": 3, "workspace_preview": False, "nodes": {
                    "write": {"op": "工作区", "action": "write_text", "path": "shared.txt", "value": "done", "overwrite": True, "edges": []},
                }},
            })
            spec = {
                "version": "ego.task.v1", "id": "multi", "title": "Multi", "prompt": "Multi",
                "workspace": {"files": {}}, "selection": {},
                "environment": {"backend": "local", "network": "disabled"},
                "execution": {"timeout_seconds": 10}, "evolution": {"allowed": False},
                "evaluation": {"pass_score": 1, "checks": []},
                "steps": [
                    {"id": "one", "prompt": "one", "workspace": {"files": {"seed.txt": "one"}}, "evaluation": {"pass_score": 1, "checks": [{"type": "file_contains", "path": "shared.txt", "value": "done"}]}},
                    {"id": "two", "prompt": "two", "resume_trajectory": True, "workspace": {"files": {}}, "evaluation": {"pass_score": 1, "checks": [{"type": "file_contains", "path": "seed.txt", "value": "one"}]}},
                ],
            }
            write_json(task_dir / "multi.json", spec)
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            created = manager.start({"task_id": "multi", "harness": "writer", "identity": "fixture"})
            deadline = time.time() + 5
            state = manager.get(created["id"])
            while state["running"] and time.time() < deadline:
                time.sleep(0.02)
                state = manager.get(created["id"])
            self.assertEqual(state["status"], "passed", state.get("error"))
            self.assertEqual([step["status"] for step in state["task_steps"]], ["passed", "passed"])
            self.assertEqual(len(state["evaluation"]["steps"]), 2)


if __name__ == "__main__":
    unittest.main()
