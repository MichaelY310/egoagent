import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "identity" / "coder" / "ego" / "skills" / "run_command" / "scripts" / "run_command.py"


def load_run_command_module():
    spec = importlib.util.spec_from_file_location("egoagent_run_command_skill", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    config_module = ModuleType("config")
    config_module.CONFIG = {"command_blacklist": []}
    with mock.patch.dict(sys.modules, {"config": config_module}):
        spec.loader.exec_module(module)
    return module


class RunCommandSkillTests(unittest.TestCase):
    def test_real_multiline_python_command_preserves_output_and_exit_code(self):
        module = load_run_command_module()
        code = "print('line-one')\nprint('line-two')"
        command = f'"{sys.executable}" -c "{code}"'

        result = json.loads(module.run_command(command))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("line-one", result["output"])
        self.assertIn("line-two", result["output"])

    def test_empty_none_stream_is_returned_as_empty_output(self):
        module = load_run_command_module()
        completed = SimpleNamespace(stdout=None, stderr=None, returncode=0)
        with mock.patch.object(module.subprocess, "run", return_value=completed):
            result = json.loads(module.run_command("no-output-command"))

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"], "")
        self.assertFalse(result["truncated"])

    def test_nonzero_exit_is_explicitly_unsuccessful(self):
        module = load_run_command_module()
        completed = SimpleNamespace(stdout="bad", stderr="", returncode=7)
        with mock.patch.object(module.subprocess, "run", return_value=completed):
            result = json.loads(module.run_command("failing-command"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)

    def test_omitted_cwd_defaults_to_the_run_workspace(self):
        module = load_run_command_module()
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            command = f'"{sys.executable}" -c "import os; print(os.getcwd())"'
            result = json.loads(module.run_command(command, _context={"workspace": temporary}))

        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(result["output"].strip()).resolve(), Path(temporary).resolve())


if __name__ == "__main__":
    unittest.main()
