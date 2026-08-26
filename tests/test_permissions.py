from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import Session
from permissions import (
    PermissionClass,
    PermissionDecision,
    PermissionRule,
    RuntimePolicy,
)
from pipeline_engine import PipelineError, PipelineRunner, RunContext


class FakeHarness:
    def __init__(self, root: Path, graph: dict, agents=None):
        self.dir = root
        self.workspace = root
        self.name = "permissions"
        self.config = {"name": self.name, "pipeline": graph}
        self.session = Session(workspace=root, save_dir=None)
        self.agents = agents or {}
        self.parent = None
        self.prompts = {}
        self._non_interactive = False


class FakeToolAgent:
    def __init__(self):
        self.name = "agent"
        self.calls = []

    def execute_tool_call(self, call, **_kwargs):
        self.calls.append(call)
        return "executed"


class PermissionPolicyTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_task_policy_denies_network_global_mutation_and_sensitive_reads(self):
        policy = RuntimePolicy.for_task(self.workspace, network="disabled", evolution_allowed=False)
        (self.workspace / ".env.local").write_text("TOKEN=hidden", encoding="utf-8")

        self.assertEqual(policy.evaluate_tool("web_search", {}).decision, PermissionDecision.DENY)
        self.assertEqual(policy.evaluate_tool("modify_harness", {}).decision, PermissionDecision.DENY)
        self.assertEqual(
            policy.evaluate_tool("read_file", {"file_path": ".env.local"}).decision,
            PermissionDecision.DENY,
        )
        self.assertEqual(
            policy.evaluate_tool("write_file", {"file_path": "result.txt"}).decision,
            PermissionDecision.ALLOW,
        )

    def test_user_modes_are_backend_policies_and_evolution_is_target_scoped(self):
        chat = RuntimePolicy.for_mode(self.workspace, "chat")
        self.assertEqual(chat.evaluate_tool("write_file", {"file_path": "a.py"}).decision, PermissionDecision.DENY)
        self.assertEqual(chat.evaluate_tool("run_command", {"command": "echo hi"}).decision, PermissionDecision.DENY)

        evaluate = RuntimePolicy.for_mode(self.workspace, "evaluate")
        self.assertEqual(evaluate.evaluate_tool("web_search", {"query": "docs"}).decision, PermissionDecision.DENY)

        evolve = RuntimePolicy.from_config(self.workspace, "evolve", {
            "allow_global_mutation": True,
            "mutation_targets": ["dante"],
        })
        allowed = evolve.evaluate_tool("evolve_capabilities", {"target_identity": "dante"})
        denied = evolve.evaluate_tool("evolve_capabilities", {"target_identity": "coder"})
        missing = evolve.evaluate_tool("evolve_capabilities", {})
        self.assertEqual(allowed.decision, PermissionDecision.ALLOW)
        self.assertEqual(denied.decision, PermissionDecision.DENY)
        self.assertEqual(missing.decision, PermissionDecision.DENY)

    def test_task_evolution_targets_are_artifact_categories(self):
        policy = RuntimePolicy.for_task(
            self.workspace,
            evolution_allowed=True,
            evolution_targets=["skill", "knowledge"],
        )
        self.assertEqual(
            policy.evaluate_tool("create_tool", {"name": "reusable_search"}).decision,
            PermissionDecision.ALLOW,
        )
        self.assertEqual(
            policy.evaluate_tool("create_skill", {"skill_name": "reusable_search"}).decision,
            PermissionDecision.ALLOW,
        )
        self.assertEqual(
            policy.evaluate_tool("create_knowledge", {"name": "paper_index"}).decision,
            PermissionDecision.ALLOW,
        )
        self.assertEqual(
            policy.evaluate_tool("create_harness", {"harness_dir": "harness/research_loop"}).decision,
            PermissionDecision.DENY,
        )

    def test_specific_mutation_scope_is_visible_in_schema_but_checked_on_call(self):
        policy = RuntimePolicy.from_config(self.workspace, "evolve", {
            "allow_global_mutation": True,
            "mutation_targets": ["dante"],
        })
        self.assertEqual(
            policy.evaluate_tool("modify_identity", {}, schema_only=True).decision,
            PermissionDecision.ALLOW,
        )
        self.assertEqual(
            policy.evaluate_tool("modify_identity", {}).decision,
            PermissionDecision.DENY,
        )

    def test_absolute_traversal_and_symlink_escape_are_denied(self):
        policy = RuntimePolicy.for_task(self.workspace)
        outside = ROOT / "README.md"
        self.assertEqual(
            policy.evaluate_tool("read_file", {"file_path": str(outside)}).decision,
            PermissionDecision.DENY,
        )
        link = self.workspace / "outside-link.md"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"symlink creation is unavailable: {error}")
        self.assertEqual(
            policy.evaluate_tool("read_file", {"file_path": str(link)}).decision,
            PermissionDecision.DENY,
        )

    def test_argument_pattern_rules_support_ask_allow_and_deny(self):
        policy = RuntimePolicy.for_mode(self.workspace, "agent")
        policy.rules.extend([
            PermissionRule(
                decision=PermissionDecision.ASK,
                permission_class=PermissionClass.NETWORK,
                tool="web_*",
                arguments={"query": "public:*"},
                reason="public searches require approval",
            ),
            PermissionRule(
                decision=PermissionDecision.DENY,
                permission_class=PermissionClass.NETWORK,
                tool="web_*",
                arguments={"query": "public:secret*"},
                reason="secret-like search denied",
            ),
        ])

        self.assertEqual(
            policy.evaluate_tool("web_search", {"query": "public:weather"}).decision,
            PermissionDecision.ASK,
        )
        denied = policy.evaluate_tool("web_search", {"query": "public:secret-token"})
        self.assertEqual(denied.decision, PermissionDecision.DENY)
        self.assertIn("secret-like", denied.reason)

    def test_graph_policy_config_matches_workspace_and_arguments(self):
        policy = RuntimePolicy.from_config(self.workspace, "agent", {
            "defaults": {"network": "deny"},
            "rules": [{
                "permission_class": "network",
                "decision": "allow",
                "tool": "web_search",
                "workspace": f"{self.workspace}*",
                "arguments": {"query": "docs:*"},
                "reason": "documentation search",
            }],
        })
        self.assertEqual(
            policy.evaluate_tool("web_search", {"query": "docs:python"}).decision,
            PermissionDecision.ALLOW,
        )
        self.assertEqual(
            policy.evaluate_tool("web_search", {"query": "private:data"}).decision,
            PermissionDecision.DENY,
        )

    def test_universal_tool_gate_denies_or_asks_before_execution(self):
        call = {"id": "call_policy", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        graph = {
            "start": "tools",
            "context": {"tool_calls": [call]},
            "nodes": {
                "tools": {
                    "id": "tools",
                    "op": "工具",
                    "agent": "agent",
                    "inputs": {"tool_calls": "$ctx.tool_calls"},
                    "edges": [],
                },
            },
        }
        denied_agent = FakeToolAgent()
        denied_policy = RuntimePolicy.from_config(self.workspace, "agent", {
            "rules": [{"permission_class": "read", "tool": "read_file", "decision": "deny", "reason": "test deny"}],
        })
        denied_harness = FakeHarness(self.workspace, graph, {"agent": denied_agent})
        denied = PipelineRunner(denied_harness, permission_policy=denied_policy).run()
        self.assertEqual(denied_agent.calls, [])
        self.assertTrue(denied.result["results"][0]["blocked"])
        self.assertIn('"tool_call_id": "call_policy"', denied_harness.session.messages[-1]["content"])

        asked_agent = FakeToolAgent()
        ask_policy = RuntimePolicy.from_config(self.workspace, "agent", {
            "rules": [{"permission_class": "read", "tool": "read_file", "decision": "ask"}],
        })
        events = []
        approved = PipelineRunner(
            FakeHarness(self.workspace, graph, {"agent": asked_agent}),
            permission_policy=ask_policy,
            get_input=lambda: "yes",
            on_output=lambda event, payload: events.append((event, payload)),
        ).run()
        self.assertEqual(len(asked_agent.calls), 1)
        self.assertEqual(approved.result["results"][0]["result"], "executed")
        self.assertTrue(any(event == "approval_required" for event, _payload in events))

    def test_secret_env_is_authorized_by_name_and_echo_is_redacted(self):
        graph = {
            "start": "process",
            "max_steps": 3,
            "nodes": {
                "process": {
                    "id": "process",
                    "op": "进程",
                    "command": sys.executable,
                    "args": ["-c", "import os; print(os.environ['PROBE_SECRET'])"],
                    "secret_env": {"PROBE_SECRET": "EGO_TEST_SECRET"},
                    "edges": [{"condition": "process_succeeded", "to": "end"}],
                },
                "end": {"id": "end", "op": "结束", "inputs": {"value": "$ctx.process_result"}, "edges": []},
            },
        }
        events = []
        with patch.dict(os.environ, {"EGO_TEST_SECRET": "ultra-private-value"}):
            runner = PipelineRunner(
                FakeHarness(self.workspace, graph),
                secret_names=["EGO_TEST_SECRET"],
                on_output=lambda event, payload: events.append((event, payload)),
            )
            context = runner.run()

        self.assertIn("[REDACTED]", context.data["process_result"]["stdout"])
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("ultra-private-value", serialized)
        self.assertIn("prompt_tokens", json.dumps({"prompt_tokens": 3}))

    def test_secret_like_raw_process_env_is_rejected(self):
        graph = {
            "start": "process",
            "max_steps": 1,
            "nodes": {
                "process": {
                    "id": "process",
                    "op": "进程",
                    "command": sys.executable,
                    "args": ["-c", "print('should not run')"],
                    "env": {"API_KEY": "plaintext"},
                    "edges": [],
                },
            },
        }
        with self.assertRaisesRegex(PipelineError, "secret_env"):
            PipelineRunner(FakeHarness(self.workspace, graph)).run()

    def test_event_sink_redacts_secret_values_but_preserves_usage_fields(self):
        graph = {"start": "end", "nodes": {"end": {"id": "end", "op": "结束", "edges": []}}}
        harness = FakeHarness(self.workspace, graph)
        captured = []
        with patch.dict(os.environ, {"EGO_TEST_SECRET": "value-to-hide"}):
            context = RunContext(
                harness=harness,
                graph=graph,
                on_output=lambda event, payload: captured.append((event, payload)),
                get_input=lambda: None,
                is_running=lambda: True,
            )
            from llm.env_config import SecretView
            context.secret_view = SecretView(["EGO_TEST_SECRET"])
            context.emit("usage", {"stdout": "value-to-hide", "prompt_tokens": 9, "access_token": "also-hide"})

        payload = captured[0][1]
        self.assertEqual(payload["stdout"], "[REDACTED]")
        self.assertEqual(payload["prompt_tokens"], 9)
        self.assertEqual(payload["access_token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
