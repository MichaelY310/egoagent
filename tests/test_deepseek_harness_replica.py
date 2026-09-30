from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent
from context_policy import TOOL_PRUNE_MARKER, apply_tool_result_pruning
from harness import Harness, get_current_harness
from loop_guard import LoopGuardError, observe_tool_trajectory, reset_loop_guard
from pipeline_engine import PipelineRunner
from pipeline_schema import validate_component_manifest, validate_pipeline


class OneToolAgent:
    """Deterministic model double used to exercise the shipped Flow itself."""

    def __init__(self, name: str = "operator"):
        self.name = name
        self.workspace = None
        self.calls = 0
        self.executed: list[str] = []
        self.tool_descriptions = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "read a fixture",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ]

    def init_environment(self):
        return None

    def build_system_prompt(self, has_tools: bool = True):
        return f"identity:{self.name}; tools:{has_tools}"

    def get_tools_desc(self):
        return copy.deepcopy(self.tool_descriptions)

    def step(self, messages, tools_desc=None, on_token=None):
        self.calls += 1
        if self.calls == 1:
            text = "I will inspect the fixture."
            tool_calls = [{
                "id": "read-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "sample.txt"})},
            }]
        else:
            text = "Verified the fixture and finished."
            tool_calls = None
        if on_token:
            on_token(text)
        harness = get_current_harness()
        working = {"role": "assistant", "name": self.name, "content": text}
        full = copy.deepcopy(working)
        if tool_calls:
            working["tool_calls"] = copy.deepcopy(tool_calls)
            full["tool_calls"] = copy.deepcopy(tool_calls)
        harness.session.record(working)
        harness.session.record_full(full)
        return text, tool_calls

    def process_text(self, text, context_messages=None, prompt_template=None):
        return text

    def process_tool_calls(self, tool_calls, context_messages=None, prompt_template=None):
        return tool_calls, []

    def execute_tool_call(self, call):
        self.executed.append(call["function"]["name"])
        result = "fixture-content"
        message = {
            "role": "user",
            "content": f'<tool_response>{json.dumps({"tool": "read_file", "content": result})}</tool_response>',
        }
        harness = get_current_harness()
        harness.session.record(copy.deepcopy(message))
        harness.session.record_full(copy.deepcopy(message))
        return result


class RepeatingToolAgent(OneToolAgent):
    """Fault-injection double: repeat one harmless observation three times."""

    def step(self, messages, tools_desc=None, on_token=None):
        self.calls += 1
        if self.calls <= 3:
            text = "I will inspect the same fixture again."
            tool_calls = [{
                "id": f"read-{self.calls}",
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "sample.txt"})},
            }]
        else:
            text = "I changed strategy after the repeat reminder and finished."
            tool_calls = None
        if on_token:
            on_token(text)
        harness = get_current_harness()
        working = {"role": "assistant", "name": self.name, "content": text}
        full = copy.deepcopy(working)
        if tool_calls:
            working["tool_calls"] = copy.deepcopy(tool_calls)
            full["tool_calls"] = copy.deepcopy(tool_calls)
        harness.session.record(working)
        harness.session.record_full(full)
        return text, tool_calls


class DeepSeekHarnessReplicaTests(unittest.TestCase):
    def test_shipped_flow_components_and_identity_are_valid(self):
        for name in ("component_repeat_tool_guard", "component_tool_result_pruner", "deepseek_harness_replica"):
            config = json.loads((ROOT / "harness" / name / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_pipeline(config["pipeline"]), [], name)
            if "component" in config:
                self.assertEqual(validate_component_manifest(config["component"]), [], name)

        agent = Agent(ROOT / "identity" / "deepseek_operator", workspace=ROOT)
        tools = {agent._short_name(name) for name in agent.tools}
        expected = {
            "read_file", "search_files", "glob_search", "ls", "apply_patch",
            "exec_command", "write_stdin", "update_plan", "create_harness",
            "web_search", "fetch_url", "browser",
        }
        self.assertTrue(expected.issubset(tools), expected - tools)

    def test_repeat_guard_is_exact_idempotent_transparent_and_advisory(self):
        calls = [
            {"action": "read_file", "arguments": {"path": "a.txt"}},
            {"action": "update_plan", "arguments": {"plan": []}},
            {"action": "read_file", "arguments": {"path": "a.txt"}},
            {"action": "read_file", "arguments": {"path": "a.txt"}},
        ]
        first = observe_tool_trajectory({}, calls, thresholds=[3, 5, 8], exclude=["update_plan"])
        self.assertTrue(first["reminded"])
        self.assertEqual(first["reminders"][0]["count"], 3)
        self.assertEqual(first["state"]["count"], 3)

        replay = observe_tool_trajectory(first["state"], calls, thresholds=[3, 5, 8], exclude=["update_plan"])
        self.assertFalse(replay["reminded"])
        self.assertEqual(replay["observed"], 0)

        changed = observe_tool_trajectory(
            replay["state"],
            calls + [{"action": "read_file", "arguments": {"path": "b.txt"}}],
            thresholds=[3, 5, 8],
            exclude=["update_plan"],
        )
        self.assertEqual(changed["state"]["count"], 1)
        self.assertFalse(changed["reminded"])
        self.assertEqual(reset_loop_guard(calls)["processed_length"], len(calls))
        with self.assertRaises(LoopGuardError):
            observe_tool_trajectory({}, calls, thresholds=[1])

    def test_tool_pruning_preserves_lossless_full_transcript(self):
        observation = "H" * 5000 + "M" * 5000 + "T" * 2000
        tool_message = {
            "role": "user",
            "content": f'<tool_response>{json.dumps({"tool": "exec_command", "content": observation})}</tool_response>',
        }
        working = [{"role": "user", "content": "run it"}, tool_message]
        full = copy.deepcopy(working)

        result = apply_tool_result_pruning(
            working,
            full,
            threshold_chars=8192,
            head_chars=4096,
            tail_chars=1024,
        )

        self.assertEqual(
            [{key: value for key, value in message.items() if key != "_message_id"} for message in result["full_messages"]],
            full,
        )
        self.assertEqual(working[1]["content"], tool_message["content"])
        rendered = result["messages"][1]["content"]
        pruned_payload = json.loads(rendered[len("<tool_response>"):-len("</tool_response>")])
        self.assertIn(TOOL_PRUNE_MARKER, pruned_payload["content"])
        self.assertIn("H" * 512, pruned_payload["content"])
        self.assertIn("T" * 512, pruned_payload["content"])
        self.assertEqual(result["stats"]["pruned_tool_results"], 1)
        self.assertGreater(result["stats"]["saved_tokens_estimated"], 0)

    def test_shipped_flow_repeat_guard_is_reachable_and_model_visible(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            (workspace / "sample.txt").write_text("fixture-content", encoding="utf-8")
            operator = RepeatingToolAgent()
            harness = Harness(
                ROOT / "harness" / "deepseek_harness_replica",
                agents={"operator": operator, "compactor": operator},
                workspace=workspace,
            )
            harness._non_interactive = True
            message = {"role": "user", "content": "Inspect sample.txt and finish."}
            harness.session.record(copy.deepcopy(message))
            harness.session.record_full(copy.deepcopy(message))
            events: list[tuple[str, dict]] = []

            result = PipelineRunner(
                harness,
                on_output=lambda event, data: events.append((event, data)),
                get_input=lambda: None,
                is_running=lambda: True,
            ).run()

            self.assertEqual(result.result, "I changed strategy after the repeat reminder and finished.")
            self.assertEqual(operator.executed, ["read_file", "read_file", "read_file"])
            reminders = [data for event, data in events if event == "loop_guard_reminder"]
            self.assertEqual([item["count"] for item in reminders], [3])
            self.assertTrue(any(
                message.get("name") == "runtime_repeat_tool_reminder"
                for message in harness.session.messages
            ))

    def test_shipped_flow_runs_one_complete_tool_round(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            (workspace / "sample.txt").write_text("fixture-content", encoding="utf-8")
            operator = OneToolAgent()
            harness = Harness(
                ROOT / "harness" / "deepseek_harness_replica",
                agents={"operator": operator, "compactor": operator},
                workspace=workspace,
            )
            harness._non_interactive = True
            message = {"role": "user", "content": "Inspect sample.txt and finish."}
            harness.session.record(copy.deepcopy(message))
            harness.session.record_full(copy.deepcopy(message))

            events: list[tuple[str, dict]] = []
            result = PipelineRunner(
                harness,
                on_output=lambda event, data: events.append((event, data)),
                get_input=lambda: None,
                is_running=lambda: True,
            ).run()

            self.assertEqual(result.result, "Verified the fixture and finished.")
            self.assertEqual(operator.executed, ["read_file"])
            self.assertGreaterEqual(operator.calls, 2)
            event_names = [name for name, _data in events]
            self.assertIn("checkpoint", event_names)
            self.assertIn("model_request", event_names)
            self.assertIn("tool", event_names)


if __name__ == "__main__":
    unittest.main()
