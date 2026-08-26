from __future__ import annotations

import json
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import Session
from environment import load_tool_from_dir
from local_api_security import (
    UnsafeResourcePath,
    is_trusted_local_origin,
    resolve_registered_root,
    resolve_resource_path,
)
from permissions import PermissionClass, PermissionDecision, RuntimePolicy, assess_tool_risk, classify_tool
from pipeline_engine import PipelineError, PipelineRunner
from process_backends import build_container_invocation
from run_failures import classify_run_failure, output_limit_notice
from secure_command import sanitized_subprocess_environment
from security_settings import load_security_settings, normalize_security_settings, save_security_settings


class FakeHarness:
    def __init__(self, root: Path, pipeline: dict, *, interactive: bool = True):
        self.dir = root
        self.workspace = root
        self.name = "security-test"
        self.config = {"name": self.name, "pipeline": pipeline}
        self.agents = {}
        self.prompts = {}
        self.session = Session(workspace=root, save_dir=None)
        self.parent = None
        self.children = []
        self.slots = {}
        self.return_mode = "last"
        self._non_interactive = not interactive


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def policy(self, **overrides):
        settings = normalize_security_settings({"profile": "balanced", **overrides})
        return RuntimePolicy.for_interactive_run(
            self.workspace,
            "agent",
            graph_config={"defaults": {"network": "allow", "process": "allow"}},
            security_settings=settings,
        )

    def test_dangerous_command_matrix_is_approval_gated(self):
        policy = self.policy()
        commands = [
            "rm -rf build",
            "Remove-Item -Recurse -Force .\\build",
            "git reset --hard HEAD~1",
            "pip install suspicious-package",
            "powershell -EncodedCommand ZQBjAGgAbwA=",
            "git push origin main --force",
        ]
        for command in commands:
            with self.subTest(command=command):
                decision = policy.evaluate_tool("run_command", {"command": command, "cwd": "."})
                self.assertEqual(decision.decision, PermissionDecision.ASK)
                self.assertIn(decision.risk.level.value, {"high", "critical"})

    def test_credentials_are_denied_even_if_harness_declares_process_only(self):
        classes = classify_tool(
            "run_command",
            {"permissions": ["process"]},
            {"command": "echo %DEEPSEEK_API_KEY%"},
        )
        self.assertIn(PermissionClass.SECRET, classes)
        decision = self.policy().evaluate_tool(
            "run_command",
            {"command": "echo %DEEPSEEK_API_KEY%"},
            {"permissions": ["process"]},
        )
        self.assertEqual(decision.decision, PermissionDecision.DENY)

    def test_declared_permissions_are_preserved_for_custom_tools(self):
        classes = classify_tool(
            "custom_connector",
            {"permissions": ["network", "write"]},
            {},
        )
        self.assertEqual(classes, {PermissionClass.NETWORK, PermissionClass.WRITE})
        decision = self.policy().evaluate_tool(
            "custom_connector",
            {},
            {"permissions": ["network", "write"]},
        )
        self.assertEqual(decision.decision, PermissionDecision.ASK)

    def test_declared_pure_completion_tool_does_not_require_approval(self):
        metadata = json.loads(
            (ROOT / "identity" / "openmanus" / "ego" / "skills" / "terminate" / "meta.json").read_text(
                encoding="utf-8"
            )
        )
        decision = self.policy().evaluate_tool(
            "terminate",
            {"status": "success", "summary": "verified"},
            metadata,
        )
        self.assertEqual(decision.decision, PermissionDecision.ALLOW)
        self.assertEqual(decision.risk.level.value, "low")

    def test_host_commands_ask_but_container_commands_can_run_without_host_approval(self):
        host = self.policy().evaluate_tool("run_command", {"command": "python -m unittest", "cwd": "."})
        self.assertEqual(host.decision, PermissionDecision.ASK)
        self.assertTrue(any(item.code == "command.host_execution" for item in host.risk.findings))

        container = self.policy(sandbox={"mode": "container"}).evaluate_tool(
            "run_command", {"command": "python -m unittest", "cwd": "."}
        )
        self.assertEqual(container.decision, PermissionDecision.ALLOW)

    def test_network_and_unknown_tools_cannot_be_silently_enabled_by_harness(self):
        policy = self.policy()
        self.assertEqual(policy.evaluate_tool("web_search", {"query": "docs"}).decision, PermissionDecision.ASK)
        self.assertEqual(
            policy.evaluate_tool("fetch_urls", {"urls": ["https://example.com"]}).decision,
            PermissionDecision.ASK,
        )
        self.assertEqual(policy.evaluate_tool("downloaded_plugin", {}).decision, PermissionDecision.ASK)

    def test_workspace_escape_and_sensitive_files_are_denied(self):
        policy = self.policy()
        outside = ROOT / "README.md"
        self.assertEqual(
            policy.evaluate_tool("read_file", {"file_path": str(outside)}).decision,
            PermissionDecision.DENY,
        )
        (self.workspace / ".env").write_text("TOKEN=secret", encoding="utf-8")
        self.assertEqual(
            policy.evaluate_tool("read_file", {"file_path": ".env"}).decision,
            PermissionDecision.DENY,
        )

    def test_recursive_search_does_not_leak_dotenv_contents(self):
        script = ROOT / "identity" / "coder" / "ego" / "skills" / "search" / "scripts" / "search_files.py"
        spec = importlib.util.spec_from_file_location("security_search_files", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        (self.workspace / ".env.test").write_text("UNIQUE_SECURITY_PROBE=secret", encoding="utf-8")
        (self.workspace / "normal.txt").write_text("UNIQUE_SECURITY_PROBE=public", encoding="utf-8")

        result = json.loads(module.search_files("UNIQUE_SECURITY_PROBE", str(self.workspace), _context={
            "security_policy": {"allow_sensitive_files": False},
        }))

        self.assertEqual(result["total_matches"], 1)
        self.assertTrue(result["matches"][0]["file"].endswith("normal.txt"))

    def test_workspace_security_settings_round_trip_and_non_unrestricted_boundary(self):
        saved = save_security_settings(self.workspace, {
            "profile": "strict",
            "workspace_only": False,
            "network_decision": "allow",
            "sandbox": {"mode": "container", "engine": "docker", "image": "python:3.12-slim"},
        })
        loaded = load_security_settings(self.workspace)
        self.assertEqual(saved, loaded)
        self.assertTrue(loaded["workspace_only"])
        self.assertEqual(loaded["sandbox"]["mode"], "container")
        self.assertTrue(loaded["sandbox"]["fail_closed"])

    def test_container_fail_closed_cannot_be_disabled_by_saved_settings(self):
        settings = normalize_security_settings({
            "sandbox": {"mode": "container", "fail_closed": False},
        })
        self.assertTrue(settings["sandbox"]["fail_closed"])

    def test_model_authored_process_environment_drops_secrets(self):
        environment = sanitized_subprocess_environment({
            "PATH": "safe-path",
            "DEEPSEEK_API_KEY": "top-secret",
            "GH_TOKEN": "also-secret",
            "NORMAL_VALUE": "not-forwarded-on-non-windows",
        })
        self.assertNotIn("DEEPSEEK_API_KEY", environment)
        self.assertNotIn("GH_TOKEN", environment)
        self.assertEqual(environment.get("PATH"), "safe-path")

    def test_container_command_never_falls_through_to_host_execution(self):
        script = ROOT / "identity" / "coder" / "ego" / "skills" / "run_command" / "scripts" / "run_command.py"
        spec = importlib.util.spec_from_file_location("security_run_command", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        marker = self.workspace / "must-not-run-on-host.txt"
        command = f'"{sys.executable}" -c "from pathlib import Path; Path(r\'{marker}\').write_text(\'bad\')"'
        with mock.patch.object(module, "execute_container_command", return_value=None):
            result = json.loads(module.run_command(command, _context={
                "workspace": str(self.workspace),
                "sandbox": {"mode": "container", "fail_closed": False},
            }))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["sandbox"]["fail_closed"])
        self.assertFalse(marker.exists())

    def test_tool_module_code_is_lazy_until_after_the_permission_gate(self):
        tool_dir = self.workspace / "untrusted_tool"
        scripts = tool_dir / "scripts"
        scripts.mkdir(parents=True)
        marker = self.workspace / "module-imported.txt"
        (tool_dir / "meta.json").write_text(json.dumps({
            "name": "untrusted_tool",
            "description": "test",
            "parameters": {"type": "object", "properties": {}},
        }), encoding="utf-8")
        (scripts / "untrusted_tool.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\ndef untrusted_tool():\n    return 'ok'\n",
            encoding="utf-8",
        )

        tool = load_tool_from_dir(tool_dir)
        self.assertIsNotNone(tool)
        self.assertFalse(marker.exists(), "catalog loading must not execute Tool module code")
        self.assertEqual(tool.func(_context={}), "ok")
        self.assertTrue(marker.exists())

    def test_local_browser_origin_boundary(self):
        for origin in (
            "http://127.0.0.1:8880",
            "http://localhost:8765",
            "http://abc123.localhost:8880",
            "vscode-webview://unit-test",
            "",
        ):
            with self.subTest(origin=origin):
                self.assertTrue(is_trusted_local_origin(origin))
        for origin in ("https://evil.example", "null", "file://local/page.html", "https://localhost.evil.example"):
            with self.subTest(origin=origin):
                self.assertFalse(is_trusted_local_origin(origin))

    def test_resource_path_boundary_rejects_cross_platform_escape_forms(self):
        safe = resolve_resource_path(self.workspace, "identity", "coder", label="identity")
        self.assertEqual(safe, (self.workspace / "identity" / "coder").resolve())
        for value in ("..", "../outside", "..\\outside", "C:outside", "bad\x00name"):
            with self.subTest(value=value), self.assertRaises(UnsafeResourcePath):
                resolve_resource_path(self.workspace, value, label="identity")

    def test_opaque_root_handles_are_authorized_by_registry_not_encoding(self):
        registered = self.workspace / "registered"
        unregistered = self.workspace / "unregistered"
        registered.mkdir()
        unregistered.mkdir()
        self.assertEqual(
            resolve_registered_root(registered, [registered], label="environment"),
            registered.resolve(),
        )
        with self.assertRaises(UnsafeResourcePath):
            resolve_registered_root(unregistered, [registered], label="environment")

    def test_container_invocation_has_hardening_and_workspace_mount(self):
        invocation = build_container_invocation(
            backend="container",
            workspace=self.workspace,
            cwd=self.workspace,
            command="python",
            args=["-c", "print('ok')"],
            environment={},
            config={
                "engine": "docker", "image": "python:3.12-slim", "network": "none",
                "read_only_root": True, "workspace_access": "rw", "pull_policy": "never",
            },
            run_id="security",
            node_id="command",
        )
        joined = " ".join(invocation.argv)
        for flag in ("--network none", "--cap-drop ALL", "no-new-privileges", "--read-only", "--pids-limit", "--memory", "--cpus"):
            self.assertIn(flag, joined)

    def test_dag_process_node_requires_explicit_approval_on_host(self):
        marker = self.workspace / "approved.txt"
        graph = {
            "start": "process",
            "max_steps": 2,
            "nodes": {
                "process": {
                    "op": "进程", "command": sys.executable,
                    "args": ["-c", "from pathlib import Path; Path('approved.txt').write_text('yes')"],
                    "edges": [],
                },
            },
        }
        events = []
        PipelineRunner(
            FakeHarness(self.workspace, graph),
            permission_policy=self.policy(),
            get_input=lambda: json.dumps({"decision": "approved"}),
            on_output=lambda event, payload: events.append((event, payload)),
        ).run()
        self.assertTrue(marker.is_file())
        self.assertIn("approval_required", [event for event, _ in events])
        self.assertIn("approval", [event for event, _ in events])

    def test_dag_process_rejection_prevents_side_effect(self):
        marker = self.workspace / "rejected.txt"
        graph = {
            "start": "process",
            "max_steps": 2,
            "nodes": {
                "process": {
                    "op": "进程", "command": sys.executable,
                    "args": ["-c", "from pathlib import Path; Path('rejected.txt').write_text('bad')"],
                    "edges": [],
                },
            },
        }
        with self.assertRaises(PipelineError):
            PipelineRunner(
                FakeHarness(self.workspace, graph),
                permission_policy=self.policy(),
                get_input=lambda: json.dumps({"decision": "rejected"}),
            ).run()
        self.assertFalse(marker.exists())

    def test_python_node_is_blocked_by_strong_sandbox_instead_of_falling_back(self):
        scripts = self.workspace / "scripts"
        scripts.mkdir()
        marker = self.workspace / "python-node-ran.txt"
        (scripts / "unsafe.py").write_text(
            "from pathlib import Path\ndef run(ctx):\n    Path('python-node-ran.txt').write_text('bad')\n    return {}\n",
            encoding="utf-8",
        )
        graph = {"start": "python", "nodes": {"python": {"op": "Python", "script": "unsafe", "edges": []}}}
        policy = self.policy(sandbox={"mode": "container"})
        with self.assertRaises(PipelineError) as raised:
            PipelineRunner(FakeHarness(self.workspace, graph), permission_policy=policy).run()
        self.assertIn("blocked while strong container sandboxing", str(raised.exception))
        self.assertFalse(marker.exists())

    def test_failure_messages_cover_limits_dns_timeout_and_output_truncation(self):
        cases = {
            "maximum context length exceeded": "context_limit",
            "token budget exceeded": "token_budget",
            "tool call budget exceeded": "tool_budget",
            "max node steps exceeded": "step_budget",
            "request timed out": "timeout",
            "getaddrinfo failed": "dns",
            "429 rate limit": "rate_limit",
        }
        for message, code in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_run_failure(message)["code"], code)
        self.assertEqual(output_limit_notice(finish_reason="length")["code"], "output_limit")


if __name__ == "__main__":
    unittest.main()
