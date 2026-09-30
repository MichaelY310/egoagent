import json
import os
import tempfile
import unittest
from pathlib import Path

from task_bench.engine import TaskBenchError, TaskBenchManager, TaskRun, _validate_spec


def _task(files):
    return {
        "version": "ego.task.v1",
        "id": "executable_fixture",
        "title": "Executable fixture",
        "prompt": "Inspect the fixture.",
        "workspace": {"files": files},
        "selection": {},
        "environment": {"backend": "local", "network": "disabled"},
        "execution": {"timeout_seconds": 10},
        "evolution": {"allowed": False},
        "evaluation": {"pass_score": 1, "checks": []},
    }


class ExecutableFixtureTests(unittest.TestCase):
    def test_executable_flag_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "task.json"
            task = _task({"tools/demo": {"content": "#!/bin/sh\n", "executable": "yes"}})
            source.write_text(json.dumps(task), encoding="utf-8")
            with self.assertRaisesRegex(TaskBenchError, "executable flag must be boolean"):
                _validate_spec(task, source)

    def test_materializer_preserves_content_and_executable_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manager = TaskBenchManager(project, task_dir=project / "tasks", runs_dir=project / "runs")
            spec = _task({"tools/demo": {"content": "#!/bin/sh\nprintf ok\n", "executable": True}})
            run = TaskRun(manager, spec, {}, "auto")
            run.workspace.mkdir(parents=True)
            run._materialize_files(spec["workspace"]["files"])

            target = run.workspace / "tools" / "demo"
            self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\nprintf ok\n")
            if os.name != "nt":
                self.assertTrue(target.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
