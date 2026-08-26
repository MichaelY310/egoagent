from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from process_backends import (
    ProcessBackendError,
    build_container_invocation,
    cleanup_container,
    container_runtime_status,
)


class ProcessBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.cwd = self.workspace / "study"
        self.cwd.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    @patch("process_backends.shutil.which", return_value=r"C:\Program Files\Docker\docker.exe")
    def test_container_invocation_has_secure_defaults_and_hides_env_values(self, _which):
        invocation = build_container_invocation(
            backend="container",
            workspace=self.workspace,
            cwd=self.cwd,
            command="python",
            args=["experiment.py", "--run", "1"],
            environment={"API_TOKEN": "secret-value", "RUN_MODE": "test"},
            config={"engine": "docker", "image": "python:3.12-slim"},
            run_id="run-1",
            node_id="experiment",
        )

        joined = " ".join(invocation.argv)
        self.assertIn("--network none", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("--security-opt no-new-privileges", joined)
        self.assertIn("--read-only", invocation.argv)
        self.assertIn("--pull never", joined)
        self.assertIn("--pids-limit 256", joined)
        self.assertIn("--memory 512m", joined)
        self.assertIn("--workdir /workspace/study", joined)
        self.assertNotIn("secret-value", joined)
        self.assertEqual(invocation.host_env["API_TOKEN"], "secret-value")
        image_index = invocation.argv.index("python:3.12-slim")
        self.assertEqual(invocation.argv[image_index + 1 :], ["python", "experiment.py", "--run", "1"])

    @patch("process_backends.shutil.which", return_value="docker")
    def test_container_rejects_privilege_escape_and_malformed_inputs(self, _which):
        common = dict(
            backend="container",
            workspace=self.workspace,
            cwd=self.cwd,
            command="python",
            args=[],
            environment={},
            run_id="run",
            node_id="node",
        )
        with self.assertRaisesRegex(ProcessBackendError, "host networking"):
            build_container_invocation(**common, config={"image": "python:3.12", "network": "host"})
        with self.assertRaisesRegex(ProcessBackendError, "image"):
            build_container_invocation(**common, config={"image": "--privileged"})
        with self.assertRaisesRegex(ProcessBackendError, "environment variable"):
            build_container_invocation(
                **(common | {"environment": {"BAD-NAME": "value"}}),
                config={"image": "python:3.12"},
            )

    @patch("process_backends.shutil.which", return_value="docker")
    @patch("process_backends.subprocess.run")
    def test_cleanup_force_removes_named_container(self, run, _which):
        invocation = build_container_invocation(
            backend="docker",
            workspace=self.workspace,
            cwd=self.workspace,
            command="python",
            args=[],
            environment={},
            config={"image": "python:3.12"},
            run_id="run",
            node_id="node",
        )
        run.return_value = subprocess.CompletedProcess([], 0, stdout=invocation.container_name, stderr="")

        result = cleanup_container(invocation)

        self.assertTrue(result["removed"])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "rm", "-f"])
        self.assertEqual(command[3], invocation.container_name)

    def test_runtime_status_reports_installed_cli_but_stopped_daemon(self):
        status = container_runtime_status("docker", timeout=10)
        self.assertIn("available", status)
        self.assertEqual(status["engine"], "docker")

    @unittest.skipUnless(os.environ.get("EGOAGENT_TEST_CONTAINER_IMAGE"), "no explicit local test image configured")
    def test_real_container_runtime_when_explicit_image_is_available(self):
        status = container_runtime_status("docker", timeout=10)
        if not status["available"]:
            self.skipTest(status.get("reason", "Docker daemon unavailable"))
        image = os.environ["EGOAGENT_TEST_CONTAINER_IMAGE"]
        invocation = build_container_invocation(
            backend="docker",
            workspace=self.workspace,
            cwd=self.workspace,
            command="python",
            args=["-c", "print('container-ok')"],
            environment={},
            config={"image": image, "pull_policy": "never"},
            run_id="real",
            node_id="smoke",
        )
        completed = subprocess.run(
            invocation.argv,
            cwd=self.workspace,
            env=invocation.host_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        cleanup_container(invocation)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("container-ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
