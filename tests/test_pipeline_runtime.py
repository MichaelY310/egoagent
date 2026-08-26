from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import EndSession, Session, get_current_harness
from agent import Agent, build_tool_image_message
from pipeline_engine import PipelineBudgetExceeded, PipelineRunner
from context_policy import context_blocks
from process_backends import ContainerInvocation
from pipeline_schema import evaluate_expression, validate_pipeline


class FakeLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or ["ok"])
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return {"choices": [{"message": {"content": self.responses[index]}}]}


class FakeAgent:
    def __init__(self, name="agent", replies=None):
        self.name = name
        self.workspace = None
        self.replies = list(replies or ["done"])
        self.calls = 0
        self.llm = FakeLLM(self.replies)
        self.tool_descriptions = []

    def init_environment(self):
        return None

    def build_system_prompt(self, has_tools=True):
        return f"identity:{self.name}; tools:{has_tools}"

    def get_tools_desc(self):
        return copy.deepcopy(self.tool_descriptions)

    def step(self, messages, tools_desc=None, on_token=None):
        self.last_messages = messages
        self.last_tools_desc = copy.deepcopy(tools_desc)
        index = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        text = self.replies[index]
        if on_token:
            on_token(text)
        harness = get_current_harness()
        message = {"role": "assistant", "name": self.name, "content": text}
        harness.session.record(message)
        harness.session.record_full(message.copy())
        return text, None

    def process_text(self, text, context_messages=None, prompt_template=None):
        return f"reviewed:{text}"

    def process_tool_calls(self, tool_calls, context_messages=None, prompt_template=None):
        return tool_calls, []

    def execute_tool_call(self, call):
        return f"ran:{call['function']['name']}"


class FakeHarness:
    def __init__(self, root: Path, pipeline: dict, agents=None):
        self.dir = root
        self.workspace = root
        self.config = {"name": "test", "pipeline": pipeline}
        self.name = "test"
        self.agents = agents or {"agent": FakeAgent()}
        self.prompts = {"test": "{value}"}
        self.session = Session(workspace=root, save_dir=None)
        self.parent = None
        self.children = []
        self.slots = {name: {} for name in self.agents}
        self.return_mode = "last"
        self._non_interactive = True

    def set_agents(self, agents):
        self.agents = agents


class PipelineRuntimeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        from harness_editor.change_tracker import clear_changes, configure_store
        configure_store(self.root / "change-journal.json")
        clear_changes()

    def tearDown(self):
        self.temp.cleanup()

    def run_graph(self, graph, agents=None, initial_data=None, events=None):
        harness = FakeHarness(self.root, graph, agents=agents)
        runner = PipelineRunner(
            harness,
            on_output=lambda event, data: (events.append((event, data)) if events is not None else None),
            get_input=lambda: None,
            is_running=lambda: True,
            initial_data=initial_data,
        )
        return harness, runner.run()

    def test_workspace_preview_does_not_replace_interactive_user_input(self):
        graph = {
            "start": "input",
            "max_steps": 2,
            "workspace_preview": True,
            "nodes": {
                "input": {"op": "输入", "edges": [{"condition": "input", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness._non_interactive = False

        result = PipelineRunner(harness, get_input=lambda: "real user task").run()

        self.assertEqual(result.result, "real user task")
        self.assertEqual(harness.session.messages[-1]["content"], "real user task")

    def test_workspace_preview_preserves_pre_recorded_one_shot_task(self):
        graph = {
            "start": "input",
            "max_steps": 2,
            "workspace_preview": True,
            "nodes": {
                "input": {"op": "输入", "edges": [{"condition": "input", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness._non_interactive = False
        harness.session.record({"role": "user", "content": "pre-recorded task"})

        result = PipelineRunner(
            harness,
            get_input=lambda: self.fail("pre-recorded task should be reused"),
        ).run()

        self.assertEqual(result.result, "pre-recorded task")

    def test_nonblocking_input_poll_records_mid_turn_steering(self):
        graph = {
            "start": "poll",
            "nodes": {
                "poll": {"op": "输入", "mode": "poll", "reuse_last": False, "edges": [{"condition": "input", "to": "done"}]},
                "done": {"op": "结束", "value": "$last.text", "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness._non_interactive = False

        result = PipelineRunner(harness, get_input=lambda timeout=None: "change direction").run()

        self.assertEqual(result.result, "change direction")
        self.assertTrue(harness.session.messages[-1]["steering"])

    def test_debugger_can_skip_side_effecting_node_with_simulated_output(self):
        events = []
        marker = self.root / "must-not-exist.txt"
        graph = {
            "start": "dangerous",
            "max_steps": 2,
            "nodes": {
                "dangerous": {
                    "op": "进程",
                    "command": sys.executable,
                    "args": ["-c", "from pathlib import Path; Path('must-not-exist.txt').write_text('called')"],
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        result = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            before_node=lambda _ctx, node_id, _node: (
                {"action": "skip", "output": {"text": "simulated"}} if node_id == "dangerous" else None
            ),
        ).run()

        self.assertFalse(marker.exists())
        self.assertEqual(result.result, "simulated")
        self.assertIn("node_skipped", [event for event, _data in events])

    def test_debugger_can_override_node_inputs_before_execution(self):
        graph = {
            "start": "done",
            "max_steps": 1,
            "nodes": {
                "done": {"op": "结束", "inputs": {"value": "original"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        result = PipelineRunner(
            harness,
            before_node=lambda _ctx, node_id, _node: (
                {"action": "override_inputs", "inputs": {"value": "edited"}} if node_id == "done" else None
            ),
        ).run()

        self.assertEqual(result.result, "edited")

    def test_debugger_can_retry_failed_node_with_edited_inputs(self):
        class FailOnceLLM(FakeLLM):
            def chat(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("simulated provider failure")
                self.last_messages = messages
                return {"choices": [{"message": {"content": "recovered"}}]}

        events = []
        agent = FakeAgent()
        agent.llm = FailOnceLLM()
        graph = {
            "start": "model",
            "max_steps": 2,
            "nodes": {
                "model": {
                    "op": "模型", "prompt": "test", "retry": {"max_attempts": 1},
                    "inputs": {"prompt": "original"},
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph, agents={"agent": agent})
        result = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            on_node_error=lambda _ctx, node_id, _node, _error: (
                {"action": "retry", "inputs": {"prompt": "edited"}} if node_id == "model" else None
            ),
        ).run()

        self.assertEqual(result.result, "recovered")
        self.assertEqual(agent.llm.calls, 2)
        self.assertEqual(result.stats.retries, 1)
        retry_event = next(data for event, data in events if event == "debug_retry")
        self.assertEqual(retry_event["input"], {"prompt": "edited"})

    def test_tool_image_attachment_is_workspace_confined_and_multimodal(self):
        image = self.root / "shot.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nsmall-test-image")

        message = build_tool_image_message({"path": str(image)}, "browser", self.root)

        self.assertEqual(message["content"][0]["type"], "text")
        self.assertTrue(message["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIsNone(build_tool_image_message({"path": str(ROOT / "README.md")}, "browser", self.root))
        self.assertIsNone(build_tool_image_message({"path": str(image)}, "browser", self.root, max_bytes=1))

    def test_tool_node_bounds_large_observations_for_custom_agents(self):
        class LargeObservationAgent(FakeAgent):
            def execute_tool_call(self, call):
                return "x" * 200

        agent = LargeObservationAgent()
        graph = {
            "start": "tools",
            "max_steps": 2,
            "context": {
                "tool_calls": [
                    {"id": "large-1", "type": "function", "function": {"name": "large", "arguments": "{}"}}
                ]
            },
            "nodes": {
                "tools": {
                    "id": "tools",
                    "op": "工具",
                    "agent": "agent",
                    "inputs": {"tool_calls": "$ctx.tool_calls"},
                    "max_observation_chars": 40,
                    "edges": [{"condition": "tools_executed", "to": "output"}],
                },
                "output": {"id": "output", "op": "结束", "inputs": {"value": "$last.results"}, "edges": []},
            },
        }

        _harness, result = self.run_graph(graph, agents={"agent": agent})

        observation = result.data["_trajectory"][0]["observation"]
        self.assertTrue(observation.startswith("x" * 40))
        self.assertIn("160 characters omitted", observation)

    def test_old_node_names_and_explicit_ports_share_one_runtime(self):
        graph = {
            "start": "think",
            "max_steps": 3,
            "nodes": {
                "think": {
                    "op": "推理",
                    "agent": "agent",
                    "outputs": {"text": "draft.text"},
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.draft.text"}, "edges": []},
            },
        }
        harness, result = self.run_graph(graph)
        self.assertEqual(result.result, "done")
        self.assertEqual(result.data["draft"]["text"], "done")
        self.assertEqual(len(harness.session.messages), 1)

    def test_debugger_gate_runs_before_each_node_and_emits_inspectable_io(self):
        events = []
        gates = []
        agent = FakeAgent(replies=["visible model answer"])
        graph = {
            "start": "think",
            "nodes": {
                "think": {
                    "op": "Agent",
                    "agent": "agent",
                    "inputs": {"api_key": "$ctx.api_key", "request": "$ctx.request"},
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph, agents={"agent": agent})
        runner = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            get_input=lambda: None,
            is_running=lambda: True,
            initial_data={"api_key": "should-not-reach-studio", "request": "hello"},
            before_node=lambda _ctx, node_id, _node: gates.append((node_id, agent.calls)),
        )

        result = runner.run()

        self.assertEqual(result.result, "visible model answer")
        self.assertEqual(gates, [("think", 0), ("done", 1)])
        self.assertEqual([event for event, _ in events].count("node_input"), 2)
        think_input = next(data for event, data in events if event == "node_input" and data["node_id"] == "think")
        self.assertEqual(think_input["input"]["api_key"], "[REDACTED]")
        model_response = next(data for event, data in events if event == "model_response")
        self.assertEqual(model_response["text"], "visible model answer")
        node_output = next(data for event, data in events if event == "node_output" and data["node_id"] == "think")
        self.assertEqual(node_output["output"]["text"], "visible model answer")

    def test_agent_node_accepts_temporary_dynamic_instructions(self):
        agent = FakeAgent()
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "none",
                    "instructions": "Goal: ${ctx.goal}; feedback: ${ctx.feedback}",
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "value": "ok", "edges": []},
            },
        }

        self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"goal": "ship", "feedback": "run tests"},
        )

        self.assertEqual(agent.last_messages[-1]["name"], "dag_instruction")
        self.assertEqual(agent.last_messages[-1]["role"], "system")
        self.assertIn("Goal: ship", agent.last_messages[-1]["content"])
        self.assertNotIn("dag_instruction", [message.get("name") for message in agent.last_messages[:-1]])

    def test_tool_result_adds_transient_non_repeating_continuation_policy(self):
        class OneToolAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.tool_descriptions = [{
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {"type": "object"}},
                }]
                self.snapshots = []

            def step(self, messages, tools_desc=None, on_token=None):
                self.snapshots.append(copy.deepcopy(messages))
                harness = get_current_harness()
                if len(self.snapshots) == 1:
                    calls = [{
                        "id": "call_read_once",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }]
                    message = {
                        "role": "assistant", "name": self.name,
                        "content": "I will inspect it.\n<tool_call>{\"name\":\"read_file\",\"arguments\":{}}</tool_call>",
                        "tool_calls": calls,
                    }
                    harness.session.record(message)
                    harness.session.record_full(copy.deepcopy(message))
                    return "I will inspect it.", calls
                message = {"role": "assistant", "name": self.name, "content": "new final evidence"}
                harness.session.record(message)
                harness.session.record_full(message.copy())
                return message["content"], None

            def execute_tool_call(self, call):
                harness = get_current_harness()
                response = {
                    "role": "user",
                    "name": "tool",
                    "content": "<tool_response>" + json.dumps({
                        "tool": "read_file",
                        "tool_call_id": call["id"],
                        "content": "file contents",
                    }) + "</tool_response>",
                }
                harness.session.record(response)
                harness.session.record_full(response.copy())
                return "file contents"

        agent = OneToolAgent()
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent", "agent": "agent", "tools": "all",
                    "instructions": "Complete the current task.",
                    "edges": [{"condition": "has_tool_calls", "to": "tools"}, {"condition": "has_text", "to": "done"}],
                },
                "tools": {"op": "Tool", "agent": "agent", "edges": [{"condition": "default", "to": "act"}]},
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }

        harness, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.result, "new final evidence")
        continuation = [item for item in agent.snapshots[-1] if item.get("name") == "runtime_tool_continuation"]
        self.assertEqual(len(continuation), 1)
        self.assertEqual(continuation[0]["role"], "system")
        self.assertIn("Do not repeat a greeting", continuation[0]["content"])
        self.assertFalse(any(item.get("name") == "runtime_tool_continuation" for item in harness.session.messages))

    def test_tool_continuation_policy_does_not_leak_between_agents(self):
        reviewer = FakeAgent(name="reviewer", replies=["independent review"])
        producer = FakeAgent(name="producer")
        graph = {
            "start": "review",
            "nodes": {
                "review": {
                    "op": "Agent", "agent": "reviewer", "tools": "none",
                    "instructions": "Review the producer's evidence independently.",
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph, agents={"producer": producer, "reviewer": reviewer})
        prior_call = {
            "role": "assistant",
            "name": "producer",
            "content": '<tool_call>{"name":"read_file","arguments":{}}</tool_call>',
            "tool_calls": [{
                "id": "producer_call",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }],
        }
        prior_result = {
            "role": "user",
            "content": "<tool_response>" + json.dumps({
                "tool": "read_file",
                "tool_call_id": "producer_call",
                "content": "producer evidence",
            }) + "</tool_response>",
        }
        harness.session.record(prior_call)
        harness.session.record(prior_result)

        result = PipelineRunner(harness, get_input=lambda: None, is_running=lambda: True).run()

        self.assertEqual(result.result, "independent review")
        self.assertFalse(any(
            item.get("name") == "runtime_tool_continuation"
            for item in reviewer.last_messages
        ))

    def test_agent_hides_excluded_tools_before_the_model_call(self):
        agent = FakeAgent()
        agent.tool_descriptions = [
            {"type": "function", "function": {"name": "read_file", "parameters": {}}},
            {"type": "function", "function": {"name": "write_file", "parameters": {}}},
            {"type": "function", "function": {"name": "run_command", "parameters": {}}},
        ]
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "all",
                    "hidden_tools": ["write*"],
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "value": "ok", "edges": []},
            },
        }

        self.run_graph(graph, agents={"agent": agent})

        names = [item["function"]["name"] for item in agent.last_tools_desc]
        self.assertEqual(names, ["read_file", "run_command"])

    def test_agent_blocks_undeclared_tool_calls_before_tool_execution(self):
        class MixedVisibilityAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "search_capabilities", "parameters": {}}},
                    {"type": "function", "function": {"name": "read_file", "parameters": {}}},
                ]

            def step(self, messages, tools_desc=None, on_token=None):
                self.last_messages = copy.deepcopy(messages)
                self.last_tools_desc = copy.deepcopy(tools_desc)
                self.calls += 1
                harness = get_current_harness()
                if self.calls == 1:
                    calls = [
                        {
                            "id": "call-search",
                            "type": "function",
                            "function": {"name": "search_capabilities", "arguments": '{"query":"context"}'},
                        },
                        {
                            "id": "call-hidden-read",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"secret.txt"}'},
                        },
                    ]
                    message = {"role": "assistant", "name": self.name, "content": "", "tool_calls": calls}
                    harness.session.record(message)
                    harness.session.record_full(copy.deepcopy(message))
                    return "", calls
                message = {"role": "assistant", "name": self.name, "content": "selected capability"}
                harness.session.record(message)
                harness.session.record_full(message.copy())
                return "selected capability", None

            def execute_tool_call(self, call):
                name = call["function"]["name"]
                self.executed.append(name)
                return f"ran:{name}"

        events = []
        agent = MixedVisibilityAgent()
        graph = {
            "start": "search",
            "max_steps": 4,
            "nodes": {
                "search": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "all",
                    "visible_tools": ["search_capabilities"],
                    "max_tool_rounds": 1,
                    "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "done"},
                    ],
                },
                "tools": {
                    "op": "Tool",
                    "agent": "agent",
                    "edges": [{"condition": "default", "to": "search"}],
                },
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }

        harness, result = self.run_graph(graph, agents={"agent": agent}, events=events)

        self.assertEqual(result.result, "selected capability")
        self.assertEqual(agent.executed, ["search_capabilities"])
        blocked = [data for event, data in events if event == "undeclared_tool_call"]
        self.assertEqual([item["tool"] for item in blocked], ["read_file"])
        self.assertTrue(any(message.get("name") == "runtime_tool_visibility" for message in harness.session.messages))

    def test_tool_call_limit_closes_every_rejected_call_before_retry(self):
        class MultiCallThenAnswerAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
                    {"type": "function", "function": {"name": "search_files", "parameters": {"type": "object"}}},
                ]

            def step(self, messages, tools_desc=None, on_token=None):
                self.last_messages = copy.deepcopy(messages)
                self.calls += 1
                harness = get_current_harness()
                if self.calls == 1:
                    calls = [
                        {
                            "id": "call-read",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                        },
                        {
                            "id": "call-search",
                            "type": "function",
                            "function": {"name": "search_files", "arguments": '{"query":"EgoAgent"}'},
                        },
                    ]
                    message = {"role": "assistant", "name": self.name, "content": "", "tool_calls": calls}
                    harness.session.record(message)
                    harness.session.record_full(copy.deepcopy(message))
                    return "", calls
                message = {"role": "assistant", "name": self.name, "content": "final answer"}
                harness.session.record(message)
                harness.session.record_full(message.copy())
                return "final answer", None

        agent = MultiCallThenAnswerAgent()
        graph = {
            "start": "answer",
            "max_steps": 3,
            "nodes": {
                "answer": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "all",
                    "max_tool_calls_per_turn": 1,
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }

        harness, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.result, "final answer")
        converter = object.__new__(Agent)
        converter.name = "agent"
        converted = converter._convert_messages_for_llm(harness.session.messages)
        batch_index = next(index for index, message in enumerate(converted) if message.get("tool_calls"))
        followups = converted[batch_index + 1:batch_index + 3]
        self.assertEqual([message.get("tool_call_id") for message in followups], ["call-read", "call-search"])
        self.assertEqual([message.get("role") for message in followups], ["tool", "tool"])
        self.assertEqual(converted[batch_index + 3]["role"], "user")

    def test_agent_tool_round_limit_hides_tools_and_forces_final_answer(self):
        class ToolUntilHiddenAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
                ]
                self.tool_snapshots = []

            def step(self, messages, tools_desc=None, on_token=None):
                self.last_messages = copy.deepcopy(messages)
                self.tool_snapshots.append(copy.deepcopy(tools_desc))
                self.calls += 1
                harness = get_current_harness()
                if tools_desc:
                    calls = [{
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                    }]
                    message = {"role": "assistant", "name": self.name, "content": "", "tool_calls": calls}
                    harness.session.record(message)
                    harness.session.record_full(copy.deepcopy(message))
                    return "", calls
                message = {"role": "assistant", "name": self.name, "content": "final from observations"}
                harness.session.record(message)
                harness.session.record_full(message.copy())
                return message["content"], None

        agent = ToolUntilHiddenAgent()
        events = []
        graph = {
            "start": "answer",
            "max_steps": 5,
            "nodes": {
                "answer": {
                    "op": "Agent", "agent": "agent", "tools": "all", "max_tool_rounds": 1,
                    "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "done"},
                    ],
                },
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.tool_calls"},
                    "edges": [{"condition": "tools_executed", "to": "answer"}],
                },
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, agents={"agent": agent}, events=events)

        self.assertEqual(result.result, "final from observations")
        self.assertEqual(len(agent.tool_snapshots[0]), 1)
        self.assertFalse(agent.tool_snapshots[1])
        self.assertEqual(agent.last_messages[-1]["name"], "runtime_tool_round_limit")
        self.assertTrue(any(event == "tool_round_limit" for event, _ in events))

    def test_mutation_request_cannot_finish_before_successful_edit_tool(self):
        class ClaimThenEditAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "multi_edit", "parameters": {"type": "object"}}},
                ]

            def step(self, messages, tools_desc=None, on_token=None):
                self.last_messages = copy.deepcopy(messages)
                self.calls += 1
                harness = get_current_harness()
                if self.calls == 1:
                    message = {"role": "assistant", "name": self.name, "content": "EDIT_OK"}
                    harness.session.record(message)
                    harness.session.record_full(message.copy())
                    return message["content"], None
                if self.calls == 2:
                    calls = [{"id": "edit-1", "type": "function", "function": {"name": "multi_edit", "arguments": "{}"}}]
                    message = {"role": "assistant", "name": self.name, "content": "", "tool_calls": calls}
                    harness.session.record(message)
                    harness.session.record_full(copy.deepcopy(message))
                    return "", calls
                message = {"role": "assistant", "name": self.name, "content": "EDIT_OK"}
                harness.session.record(message)
                harness.session.record_full(message.copy())
                return message["content"], None

        agent = ClaimThenEditAgent()
        events = []
        graph = {
            "start": "input",
            "max_steps": 8,
            "nodes": {
                "input": {"op": "Input", "edges": [{"condition": "input", "to": "act"}]},
                "act": {
                    "op": "Agent", "agent": "agent", "tools": "all",
                    "require_tool_for_mutations": True,
                    "required_tool_patterns": ["multi_edit"],
                    "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "done"},
                    ],
                },
                "tools": {"op": "Tool", "agent": "agent", "edges": [{"condition": "default", "to": "act"}]},
                "done": {"op": "End", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph, agents={"agent": agent})
        harness.session.record({"role": "user", "content": "Modify file demo.py and replace the value."})
        harness.session.record_full({"role": "user", "content": "Modify file demo.py and replace the value."})
        result = PipelineRunner(harness, on_output=lambda event, data: events.append((event, data))).run()
        self.assertEqual(result.result, "EDIT_OK")
        self.assertEqual(agent.calls, 3)
        self.assertTrue(any(event == "required_tool_missing" for event, _ in events))
        self.assertIn("multi_edit", result.data["_turn_executed_tools"])

    def test_model_request_records_default_visible_tool_schemas(self):
        agent = FakeAgent()
        agent.tool_descriptions = [
            {"type": "function", "function": {"name": "create_harness", "parameters": {}}},
            {"type": "function", "function": {"name": "read_file", "parameters": {}}},
        ]
        events = []
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent", "agent": "agent", "tools": "all",
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "value": "ok", "edges": []},
            },
        }

        self.run_graph(graph, agents={"agent": agent}, events=events)

        request = next(data for event, data in events if event == "model_request")
        self.assertEqual(
            [item["function"]["name"] for item in request["tools"]],
            ["create_harness", "read_file"],
        )
        self.assertEqual(agent.last_tools_desc, request["tools"])

    def test_agent_can_auto_continue_once_after_context_compaction(self):
        agent = FakeAgent(replies=["premature final", "actual final"])
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "none",
                    "inputs": {"compacted": "$ctx.compacted"},
                    "auto_continue_when": "compacted == true",
                    "auto_continue_prompt": "continue",
                    "auto_continue_to": "clear",
                    "max_auto_continuations": 1,
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "clear": {
                    "op": "数据",
                    "action": "set",
                    "key": "compacted",
                    "value": False,
                    "edges": [{"condition": "default", "to": "act"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.act.text"}, "edges": []},
            },
        }

        harness, result = self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"compacted": True},
        )

        self.assertEqual(result.result, "actual final")
        self.assertEqual(result.stats.model_calls, 2)
        self.assertEqual(agent.calls, 2)
        continuations = [message for message in harness.session.messages if message.get("name") == "runtime_auto_continue"]
        self.assertEqual([message["content"] for message in continuations], ["continue"])
        self.assertTrue(any(message.get("name") == "runtime_auto_continue" for message in agent.last_messages))

    def test_context_auto_compaction_is_thresholded_and_persists_the_summary(self):
        agent = FakeAgent()
        agent.llm.responses = ["condensed current state"]
        history = [
            {"role": "user", "content": "request " * 120},
            {"role": "assistant", "content": "analysis " * 120},
        ]
        graph = {
            "start": "context",
            "budget": {"max_model_calls": 2},
            "nodes": {
                "context": {
                    "op": "上下文",
                    "action": "auto_compact",
                    "agent": "agent",
                    "source": "$ctx.history",
                    "context_limit_tokens": 100,
                    "max_output_tokens": 10,
                    "compaction_buffer_cap": 5,
                    "persist_session": True,
                    "output_var": "working_context",
                    "edges": [{"condition": "context_ready", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.context.compacted"}, "edges": []},
            },
        }

        harness, result = self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"history": history},
        )

        self.assertTrue(result.result)
        self.assertTrue(result.data["context_compacted"])
        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(harness.session.messages[0]["name"], "context_summary")
        self.assertEqual(harness.session.messages[0]["content"], "condensed current state")
        self.assertEqual(harness.session.full_messages, [])

    def test_periodic_curator_reuses_pressure_view_until_a_new_review_batch_exists(self):
        graph = {
            "start": "context",
            "nodes": {
                "context": {
                    "op": "上下文",
                    "action": "curate",
                    "agent": "agent",
                    "source": "$session.full_messages",
                    "review_interval": 5,
                    "protect_recent_turns": 1,
                    "persist_session": True,
                    "edges": [{"condition": "context_ready", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.context.pressure_view_reused"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness.session.full_messages = [
            {"role": "user", "content": "original long history"},
            {"role": "assistant", "content": "original long answer"},
            {"role": "user", "content": "latest request"},
        ]
        harness.session.messages = [
            {"role": "system", "name": "context_compactor", "content": "compressed durable state"},
            {"role": "user", "content": "latest request"},
        ]
        harness.session.state["context_governance"] = {
            "pressure_compactions": [{"created_at": 1}],
            "pressure_stats": {"before_tokens_estimated": 9000, "after_tokens_estimated": 400},
            "reviewed_turn_ids": [],
        }
        result = PipelineRunner(harness, get_input=lambda: None, is_running=lambda: True).run()
        self.assertTrue(result.result)
        self.assertEqual(result.stats.model_calls, 0)
        self.assertEqual(harness.session.messages[0]["content"], "compressed durable state")
        self.assertEqual(harness.session.full_messages[0]["content"], "original long history")

    def test_agent_model_call_passively_triggers_model_authored_pressure_compaction(self):
        history = [
            {"role": "user", "content": "Old durable requirement: keep port 7319. " * 80},
            {
                "role": "assistant",
                "content": "The decisive answer is RRF.",
                "reasoning_content": "routine dead-end analysis " * 800 + "Aha: use RRF.",
            },
            {"role": "user", "content": "Continue the task and keep port 7319."},
        ]
        blocks = context_blocks(history, protect_recent_turns=1)
        old_requirement = next(block for block in blocks if block.kind == "user_requirement" and not block.protected)
        old_reasoning = next(block for block in blocks if block.kind == "assistant_reasoning")
        plan = {
            "blocks": [
                {"block_id": old_requirement.id, "action": "summarize", "reason": "durable", "summary": "Keep port 7319."},
                {"block_id": old_reasoning.id, "action": "simplify_reasoning", "reason": "pre-aha noise", "summary": "Aha: use RRF."},
            ],
            "continuation_summary": "Keep port 7319 and use RRF.",
        }
        agent = FakeAgent(replies=["final response"])
        agent.llm.responses = [json.dumps(plan)]
        events = []
        graph = {
            "start": "infer",
            "budget": {"max_model_calls": 3},
            "context_management": {
                "enabled": True,
                "context_limit_tokens": 2048,
                "high_watermark": 0.6,
                "target_ratio": 0.35,
                "reserved_output_tokens": 64,
                "protect_recent_turns": 1,
                "compactor_max_tokens": 512,
            },
            "nodes": {
                "infer": {
                    "op": "推理",
                    "agent": "agent",
                    "inputs": {"messages": "$ctx.history"},
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.infer.text"}, "edges": []},
            },
        }
        harness, result = self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"history": history},
            events=events,
        )
        self.assertEqual(result.result, "final response")
        self.assertEqual(result.stats.model_calls, 2)
        self.assertEqual(agent.llm.calls, 1)
        self.assertEqual(agent.calls, 1)
        rendered = json.dumps(agent.last_messages, ensure_ascii=False)
        self.assertIn("Keep port 7319", rendered)
        self.assertIn("Aha: use RRF", rendered)
        self.assertNotIn("routine dead-end analysis routine dead-end analysis", rendered)
        names = [name for name, _payload in events]
        self.assertIn("context_pressure", names)
        self.assertIn("context_compaction_started", names)
        self.assertIn("context_compacted", names)

    def test_input_node_can_request_a_fresh_user_message(self):
        graph = {
            "start": "clarify",
            "nodes": {
                "clarify": {
                    "op": "输入",
                    "reuse_last": False,
                    "prompt_text": "Please clarify",
                    "outputs": {"text": "clarification"},
                    "edges": [{"condition": "input", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.clarification"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness._non_interactive = False
        harness.session.record({"role": "user", "content": "original"})
        events = []
        result = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            get_input=lambda: "new detail",
            is_running=lambda: True,
        ).run()

        self.assertEqual(result.result, "new detail")
        self.assertEqual(harness.session.messages[-1]["content"], "new detail")
        self.assertTrue(any(event == "input_required" for event, _ in events))

    def test_agent_stuck_guard_injects_a_strategy_change_prompt(self):
        agent = FakeAgent("agent", ["same", "same", "different"])
        graph = {
            "start": "act",
            "max_steps": 5,
            "nodes": {
                "act": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "none",
                    "duplicate_threshold": 1,
                    "edges": [{"condition": "has_text", "to": "done"}, {"condition": "stuck", "to": "act"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.act.text"}, "edges": []},
            },
        }
        events = []
        harness = FakeHarness(self.root, graph, agents={"agent": agent})
        harness.session.record({"role": "assistant", "name": "agent", "content": "same"})
        result = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            get_input=lambda: None,
            is_running=lambda: True,
        ).run()

        self.assertEqual(agent.calls, 3)
        self.assertEqual(result.result, "different")
        self.assertTrue(any(message.get("_op") == "stuck_guard" for message in harness.session.messages))
        self.assertTrue(any(event == "agent_stuck" for event, _ in events))

    def test_agent_internal_repetition_guard_routes_to_recovery(self):
        looping = "alpha beta gamma delta epsilon zeta eta theta " * 30
        agent = FakeAgent("agent", [looping, "recovered with a concrete action"])
        graph = {
            "start": "act",
            "max_steps": 5,
            "nodes": {
                "act": {
                    "op": "Agent",
                    "agent": "agent",
                    "tools": "none",
                    "repetition_ngram_size": 8,
                    "repetition_ratio_threshold": 0.18,
                    "repetition_min_tokens": 100,
                    "edges": [{"condition": "has_text", "to": "done"}, {"condition": "stuck", "to": "act"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.act.text"}, "edges": []},
            },
        }
        events = []
        harness = FakeHarness(self.root, graph, agents={"agent": agent})
        result = PipelineRunner(
            harness,
            on_output=lambda event, data: events.append((event, data)),
            get_input=lambda: None,
            is_running=lambda: True,
        ).run()

        self.assertEqual(result.result, "recovered with a concrete action")
        stuck_events = [data for event, data in events if event == "agent_stuck"]
        self.assertEqual(stuck_events[0]["reason"], "internal_ngram_repetition")
        self.assertGreater(stuck_events[0]["repetition_ratio"], 0.18)

    def test_empty_agent_response_gets_corrective_retry(self):
        agent = FakeAgent("agent", ["", "concrete answer"])
        graph = {
            "start": "act",
            "nodes": {
                "act": {
                    "op": "Agent", "agent": "agent", "tools": "none", "max_empty_responses": 1,
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.act.text"}, "edges": []},
            },
        }

        harness, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.result, "concrete answer")
        self.assertEqual(agent.calls, 2)
        self.assertEqual(agent.last_messages[-1]["name"], "runtime_empty_response")
        self.assertTrue(any(message.get("name") == "runtime_empty_response" for message in harness.session.messages))

    def test_tool_review_policy_allows_asks_and_denies_without_an_llm_call(self):
        calls = [
            {"id": "1", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "2", "function": {"name": "run_command", "arguments": '{"command":"test"}'}},
            {"id": "3", "function": {"name": "write_file", "arguments": "{}"}},
        ]
        graph = {
            "start": "review",
            "nodes": {
                "review": {
                    "op": "工具审查",
                    "agent": "agent",
                    "review_mode": "policy",
                    "default_permission": "deny",
                    "policies": [
                        {"tool": "read*", "permission": "allow"},
                        {"tool": "run_command", "permission": "ask"},
                    ],
                    "inputs": {"tool_calls": "$ctx.calls"},
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.review"}, "edges": []},
            },
        }
        events = []
        harness, result = self.run_graph(graph, initial_data={"calls": calls}, events=events)

        self.assertEqual([call["function"]["name"] for call in result.result["tool_calls"]], ["read_file"])
        self.assertEqual(len(result.result["blocked"]), 2)
        self.assertEqual(result.stats.model_calls, 0)
        self.assertTrue(any(event == "approval_required" for event, _ in events))

    def test_tool_review_can_use_continue_style_first_match_precedence(self):
        call = {"id": "1", "function": {"name": "write_file", "arguments": "{}"}}
        graph = {
            "start": "review",
            "nodes": {
                "review": {
                    "op": "工具审查",
                    "agent": "agent",
                    "review_mode": "policy",
                    "policy_match": "first",
                    "default_permission": "deny",
                    "policies": [
                        {"tool": "write*", "permission": "exclude"},
                        {"tool": "*", "permission": "allow"},
                    ],
                    "inputs": {"tool_calls": "$ctx.calls"},
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.review"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"calls": [call]})

        self.assertIsNone(result.result["tool_calls"])
        self.assertEqual(len(result.result["blocked"]), 1)

    def test_tool_execution_records_redacted_replayable_trajectory(self):
        calls = [{"id": "1", "function": {"name": "demo", "arguments": '{"text":"secret","value":3}'}}]
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具",
                    "agent": "agent",
                    "inputs": {"tool_calls": "$ctx.calls"},
                    "sensitive_fields": ["text"],
                    "edges": [{"condition": "tools_executed", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx._trajectory"}, "edges": []},
            },
        }
        events = []
        _, result = self.run_graph(graph, initial_data={"calls": calls}, events=events)

        self.assertEqual(result.result[0]["action"], "demo")
        self.assertEqual(result.result[0]["arguments"]["text"], "[REDACTED]")
        self.assertEqual(result.result[0]["arguments"]["value"], 3)
        self.assertTrue(any(event == "action_observation" for event, _ in events))

    def test_tool_batch_can_interrupt_after_a_page_changing_action(self):
        calls = [
            {"id": "1", "function": {"name": "browser", "arguments": '{"action":"navigate"}'}},
            {"id": "2", "function": {"name": "browser", "arguments": '{"action":"click"}'}},
        ]
        agent = FakeAgent("agent")
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                    "interrupt_when": "tool == 'browser' and arguments.action == 'navigate'",
                    "edges": [{"condition": "tools_executed", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx._trajectory"}, "edges": []},
            },
        }
        events = []
        _, result = self.run_graph(graph, agents={"agent": agent}, initial_data={"calls": calls}, events=events)

        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0]["arguments"]["action"], "navigate")
        self.assertTrue(any(event == "tool_batch_interrupted" for event, _ in events))

    def test_tool_human_handoff_has_explicit_route_and_run_cleanup(self):
        class HandoffAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.cleaned = False

            def execute_tool_call(self, call):
                return {
                    "status": "human_required",
                    "requires_human": True,
                    "reason": "CAPTCHA",
                    "path": "screenshot.png",
                }

            def close_runtime_resources(self):
                self.cleaned = True
                return [{"resource": "browser_session", "result": {"closed": True}}]

        agent = HandoffAgent()
        call = {"id": "handoff", "function": {"name": "browser", "arguments": '{"action":"handoff"}'}}
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具",
                    "agent": "agent",
                    "inputs": {"tool_calls": "$ctx.calls"},
                    "outputs": {"human_required": "handoff"},
                    "edges": [
                        {"condition": "human_required", "to": "human"},
                        {"condition": "tools_executed", "to": "wrong"},
                    ],
                },
                "human": {"op": "结束", "inputs": {"value": "$ctx.handoff.required"}, "edges": []},
                "wrong": {"op": "结束", "value": False, "edges": []},
            },
        }
        events = []

        _, result = self.run_graph(graph, agents={"agent": agent}, initial_data={"calls": [call]}, events=events)

        self.assertTrue(result.result)
        self.assertTrue(agent.cleaned)
        self.assertTrue(any(event == "human_required" for event, _payload in events))
        self.assertTrue(any(event == "runtime_resources_closed" for event, _payload in events))

    def test_tool_trajectory_detects_repeated_action_observation_loop(self):
        call = {"id": "same", "function": {"name": "demo", "arguments": '{"value":1}'}}
        graph = {
            "start": "first",
            "nodes": {
                "first": {"op": "工具", "inputs": {"tool_calls": "$ctx.calls"}, "stuck_threshold": 3, "edges": [{"condition": "tools_executed", "to": "second"}]},
                "second": {"op": "工具", "inputs": {"tool_calls": "$ctx.calls"}, "stuck_threshold": 3, "edges": [{"condition": "tools_executed", "to": "third"}]},
                "third": {"op": "工具", "inputs": {"tool_calls": "$ctx.calls"}, "stuck_threshold": 3, "edges": [{"condition": "stuck", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx._tool_stuck.reason"}, "edges": []},
            },
        }
        events = []

        harness, result = self.run_graph(graph, initial_data={"calls": [call]}, events=events)

        self.assertIn("repeated 3 times", result.result)
        self.assertEqual(len(result.data["_trajectory"]), 3)
        self.assertEqual(harness.session.messages[-1]["name"], "runtime_stuck_detector")
        self.assertTrue(any(event == "tool_stuck" for event, _ in events))

    def test_tool_stuck_signature_can_ignore_annotations_and_changing_observations(self):
        calls = {
            f"call{index}": [{
                "id": f"same-{index}",
                "function": {
                    "name": "arc_act",
                    "arguments": json.dumps({"action_name": "ACTION1", "prediction": f"guess-{index}"}),
                },
            }]
            for index in range(3)
        }
        common = {
            "op": "工具",
            "stuck_threshold": 3,
            "stuck_ignore_arguments": ["prediction"],
            "stuck_include_observation": False,
        }
        graph = {
            "start": "first",
            "nodes": {
                "first": {**common, "inputs": {"tool_calls": "$ctx.call0"}, "edges": [{"condition": "tools_executed", "to": "second"}]},
                "second": {**common, "inputs": {"tool_calls": "$ctx.call1"}, "edges": [{"condition": "tools_executed", "to": "third"}]},
                "third": {**common, "inputs": {"tool_calls": "$ctx.call2"}, "edges": [{"condition": "stuck", "to": "done"}]},
                "done": {"op": "结束", "value": "$ctx._tool_stuck.reason", "edges": []},
            },
        }
        _harness, result = self.run_graph(graph, initial_data=calls)
        self.assertIn("repeated 3 times", result.result)

    def test_tool_batch_discards_calls_after_terminal_tool(self):
        class RecordingAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []

            def execute_tool_call(self, call):
                name = call["function"]["name"]
                self.executed.append(name)
                return f"observed:{name}"

        agent = RecordingAgent()
        calls = [
            {"id": name, "function": {"name": name, "arguments": "{}"}}
            for name in ["read_file", "finish", "write_file"]
        ]
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                    "truncate_after_tools": ["finish"],
                    "edges": [{"condition": "tools_executed", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.tools", "edges": []},
            },
        }
        events = []

        harness, result = self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"calls": calls},
            events=events,
        )

        self.assertEqual(agent.executed, ["read_file", "finish"])
        self.assertEqual([call["function"]["name"] for call in result.result["dropped_calls"]], ["write_file"])
        self.assertEqual(harness.session.messages[-1]["name"], "runtime_tool_batch_truncation")
        self.assertTrue(any(event == "tool_batch_truncated" for event, _ in events))

    def test_tool_batch_keeps_only_first_call_to_exclusive_tool(self):
        class RecordingAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []

            def execute_tool_call(self, call):
                name = call["function"]["name"]
                self.executed.append(name)
                return f"observed:{name}"

        agent = RecordingAgent()
        calls = [
            {"id": "1", "function": {"name": "edit_file", "arguments": '{"path":"a"}'}},
            {"id": "2", "function": {"name": "edit_file", "arguments": '{"path":"b"}'}},
            {"id": "3", "function": {"name": "read_file", "arguments": '{}'}},
        ]
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {"op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"}, "exclusive_tools": ["edit_file"], "edges": [{"condition": "tools_executed", "to": "done"}]},
                "done": {"op": "结束", "value": "$node.tools", "edges": []},
            },
        }
        events = []
        harness, result = self.run_graph(graph, agents={"agent": agent}, initial_data={"calls": calls}, events=events)
        self.assertEqual(agent.executed, ["edit_file", "read_file"])
        self.assertEqual([call["id"] for call in result.result["dropped_calls"]], ["2"])
        self.assertTrue(any(message.get("name") == "runtime_exclusive_tool_deduplication" for message in harness.session.messages))
        self.assertTrue(any(event == "exclusive_tool_calls_dropped" for event, _ in events))

    def test_tool_batch_discards_position_guard_and_later_calls(self):
        class RecordingAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []

            def execute_tool_call(self, call):
                name = call["function"]["name"]
                self.executed.append(name)
                return f"observed:{name}"

        agent = RecordingAgent()
        calls = [
            {"id": "1", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "2", "function": {"name": "done", "arguments": "{}"}},
            {"id": "3", "function": {"name": "write_file", "arguments": "{}"}},
        ]
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {"op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"}, "only_first_tools": ["done"], "edges": [{"condition": "tools_executed", "to": "finished"}]},
                "finished": {"op": "结束", "value": "$node.tools", "edges": []},
            },
        }
        events = []
        harness, result = self.run_graph(graph, agents={"agent": agent}, initial_data={"calls": calls}, events=events)
        self.assertEqual(agent.executed, ["read_file"])
        self.assertEqual([call["id"] for call in result.result["dropped_calls"]], ["2", "3"])
        self.assertTrue(any(message.get("name") == "runtime_tool_position_guard" for message in harness.session.messages))
        self.assertTrue(any(event == "tool_position_guard" for event, _ in events))

    def test_terminal_tool_can_route_out_of_the_inner_agent_loop(self):
        class RecordingAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []

            def execute_tool_call(self, call):
                name = call["function"]["name"]
                self.executed.append(name)
                return f"observed:{name}"

        agent = RecordingAgent()
        calls = [
            {"id": name, "function": {"name": name, "arguments": "{}"}}
            for name in ["read_file", "finish", "write_file"]
        ]
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                    "truncate_after_tools": ["finish"], "terminal_tools_to": "judge",
                    "edges": [{"condition": "tools_executed", "to": "wrong"}],
                },
                "judge": {"op": "结束", "value": "$ctx._terminal_tool", "edges": []},
                "wrong": {"op": "结束", "value": "wrong", "edges": []},
            },
        }
        events = []

        _, result = self.run_graph(
            graph,
            agents={"agent": agent},
            initial_data={"calls": calls},
            events=events,
        )

        self.assertEqual(agent.executed, ["read_file", "finish"])
        self.assertEqual(result.result, {"tool": "finish", "to": "judge"})
        self.assertTrue(any(event == "terminal_tool" for event, _ in events))

    def test_tool_error_streak_nudges_once_at_threshold_before_hard_stuck(self):
        class ErrorAgent(FakeAgent):
            def execute_tool_call(self, _call):
                return "Error: same failure"

        previous = [
            {
                "action": "demo", "arguments": {"value": 1}, "ok": False,
                "observation": "Error: same failure",
            }
            for _ in range(2)
        ]
        call = {"id": "same", "function": {"name": "demo", "arguments": '{"value":1}'}}
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                    "error_nudge_threshold": 3, "error_stuck_threshold": 4,
                    "edges": [{"condition": "error_nudge", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx._tool_error_nudge", "edges": []},
            },
        }

        harness, result = self.run_graph(
            graph,
            agents={"agent": ErrorAgent()},
            initial_data={"calls": [call], "_trajectory": previous},
        )

        self.assertEqual(result.result["streak"], 3)
        self.assertIn("same failure", result.result["nudge"])
        self.assertEqual(harness.session.messages[-1]["name"], "runtime_tool_error_nudge")
        self.assertNotIn("_tool_stuck", result.data)

    def test_tool_error_streak_hard_stops_after_nudge_threshold_is_exceeded(self):
        class ErrorAgent(FakeAgent):
            def execute_tool_call(self, _call):
                return "Error: same failure"

        previous = [
            {
                "action": "demo", "arguments": {"value": 1}, "ok": False,
                "observation": "Error: same failure",
            }
            for _ in range(3)
        ]
        call = {"id": "same", "function": {"name": "demo", "arguments": '{"value":1}'}}
        graph = {
            "start": "tools",
            "nodes": {
                "tools": {
                    "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                    "error_nudge_threshold": 3, "error_stuck_threshold": 4,
                    "edges": [{"condition": "stuck", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx._tool_stuck.reason", "edges": []},
            },
        }

        _, result = self.run_graph(
            graph,
            agents={"agent": ErrorAgent()},
            initial_data={"calls": [call], "_trajectory": previous},
        )

        self.assertIn("failed 4 times", result.result)
        self.assertNotIn("_tool_error_nudge", result.data)

    def test_safe_if_and_data_nodes_replace_python_for_common_logic(self):
        graph = {
            "start": "save",
            "nodes": {
                "save": {
                    "op": "保存数据",
                    "key": "score",
                    "value": 9,
                    "edges": [{"condition": "default", "to": "if"}],
                },
                "if": {
                    "op": "条件",
                    "condition": "ctx.score >= 8 and exists(ctx.score)",
                    "edges": [
                        {"condition": "true", "to": "pass"},
                        {"condition": "false", "to": "fail"},
                    ],
                },
                "pass": {"op": "结束", "value": "passed", "edges": []},
                "fail": {"op": "结束", "value": "failed", "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, "passed")
        self.assertTrue(evaluate_expression("ctx.score == 9", {"ctx": {"score": 9}}))
        self.assertTrue(evaluate_expression("contains(lower(ctx.reply), 'decision made: novel')", {"ctx": {"reply": "Decision Made: Novel."}}))

    def test_data_filter_selects_items_without_python(self):
        graph = {
            "start": "select",
            "nodes": {
                "select": {
                    "op": "数据",
                    "action": "filter",
                    "key": "novel_ideas",
                    "source": "$ctx.ideas",
                    "condition": "item.novel == true and item.score >= 6",
                    "output_var": "selected",
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.selected"}, "edges": []},
            },
        }
        ideas = [
            {"name": "a", "novel": True, "score": 8},
            {"name": "b", "novel": False, "score": 9},
            {"name": "c", "novel": True, "score": 4},
        ]

        _, result = self.run_graph(graph, initial_data={"ideas": ideas})

        self.assertEqual(result.result, [ideas[0]])
        self.assertEqual(result.data["novel_ideas"], [ideas[0]])

    def test_data_aggregate_fields_reproduces_review_ensemble_score_rounding(self):
        reviews = [
            {"Overall": 5, "Confidence": 3, "Soundness": 2},
            {"Overall": 7, "Confidence": 4, "Soundness": 4},
            {"Overall": 8, "Confidence": 5, "Soundness": 3},
        ]
        graph = {
            "start": "average",
            "nodes": {
                "average": {
                    "op": "数据", "action": "aggregate_fields", "key": "averages",
                    "source": "$ctx.reviews", "fields": ["Overall", "Confidence", "Soundness"],
                    "limits": {"Overall": [1, 10], "Confidence": [1, 5], "Soundness": [1, 4]},
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.averages", "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"reviews": reviews})

        self.assertEqual(result.result, {"Overall": 7, "Confidence": 4, "Soundness": 3})

    def test_data_evaluate_slice_and_unique_avoid_python_escape_hatches(self):
        graph = {
            "start": "decrement",
            "context": {"depth": 3, "text": "abcdefghij", "items": ["a", "b", "a"]},
            "nodes": {
                "decrement": {"op": "数据", "action": "evaluate", "key": "next_depth", "expression": "max(0, ctx.depth - 1)", "edges": [{"condition": "default", "to": "trim"}]},
                "trim": {"op": "数据", "action": "evaluate", "key": "trimmed", "expression": "ctx.text[:int(len(ctx.text) * 0.9)] if ctx.depth > 1 else ctx.text", "edges": [{"condition": "default", "to": "dedupe"}]},
                "dedupe": {"op": "数据", "action": "unique", "key": "unique_items", "source": "$ctx.items", "edges": [{"condition": "default", "to": "slice"}]},
                "slice": {"op": "数据", "action": "slice", "key": "first", "source": "$ctx.unique_items", "end_index": 1, "edges": [{"condition": "default", "to": "word_trim"}]},
                "word_trim": {"op": "数据", "action": "trim_words", "key": "recent", "source": ["old words are removed", "new facts survive"], "max_words": 3, "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": {"depth": "$ctx.next_depth", "text": "$ctx.trimmed", "items": "$ctx.first", "recent": "$ctx.recent"}}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, {"depth": 2, "text": "abcdefghi", "items": ["a"], "recent": ["new facts survive"]})

    def test_data_range_creates_bounded_loop_slots_without_python(self):
        graph = {
            "start": "slots",
            "context": {"iterations": 4},
            "nodes": {
                "slots": {"op": "数据", "action": "range", "key": "learning_slots", "range_start": 1, "range_stop": "$ctx.iterations", "range_step": 1, "max_items": 10, "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "value": "$ctx.learning_slots", "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, [1, 2, 3])

    def test_map_max_count_can_be_driven_by_typed_context(self):
        graph = {
            "start": "map",
            "context": {"items": [1, 2, 3], "breadth": 2},
            "nodes": {
                "map": {"op": "映射", "source": "$ctx.items", "item_var": "item", "body_start": "take", "join": "join", "max_count": "$ctx.breadth", "output_var": "branches", "edges": []},
                "take": {"op": "数据", "action": "get", "key": "item", "edges": [{"condition": "default", "to": "join"}]},
                "join": {"op": "合并", "source": "$ctx.branches", "strategy": "values", "output_var": "values", "edges": [{"condition": "joined", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx.values"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, [1, 2])

    def test_join_values_unwraps_parallel_branch_metadata(self):
        graph = {
            "start": "join",
            "nodes": {
                "join": {
                    "op": "合并",
                    "strategy": "values",
                    "source": "$ctx.branches",
                    "output_var": "values",
                    "edges": [{"condition": "joined", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.values"}, "edges": []},
            },
        }
        branches = [
            {"name": "a", "result": {"novel": True}},
            {"name": "b", "result": None, "last": {"value": {"novel": False}}},
        ]

        _, result = self.run_graph(graph, initial_data={"branches": branches})

        self.assertEqual(result.result, [{"novel": True}, {"novel": False}])

    def test_join_flatten_unwraps_and_flattens_one_list_layer(self):
        graph = {
            "start": "join",
            "nodes": {
                "join": {"op": "合并", "strategy": "flatten", "source": "$ctx.branches", "output_var": "values", "edges": [{"condition": "joined", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx.values"}, "edges": []},
            },
        }
        branches = [{"result": [1, 2]}, {"last": {"value": [3]}}, {"result": 4}]
        _, result = self.run_graph(graph, initial_data={"branches": branches})
        self.assertEqual(result.result, [1, 2, 3, 4])

    def test_process_node_captures_typed_evidence_and_artifacts(self):
        graph = {
            "start": "run",
            "budget": {"max_process_calls": 1},
            "resource_limits": {"cpu": 1},
            "nodes": {
                "run": {
                    "op": "进程",
                    "command": "$ctx.python",
                    "args": [
                        "-c",
                        "from pathlib import Path; Path('artifact.txt').write_text('ok', encoding='utf-8'); print('measured=1')",
                    ],
                    "resources": {"cpu": 1},
                    "artifacts": ["artifact.txt"],
                    "output_var": "execution",
                    "timeout_seconds": 5,
                    "edges": [{"condition": "process_succeeded", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.execution"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"python": sys.executable})

        self.assertEqual(result.result["exit_code"], 0)
        self.assertIn("measured=1", result.result["stdout"])
        self.assertEqual(result.result["artifacts"], ["artifact.txt"])
        self.assertEqual(result.stats.process_calls, 1)

    def test_container_process_backend_preserves_typed_contract_and_cleanup(self):
        invocation = ContainerInvocation(
            argv=[sys.executable, "-c", "print('isolated-evidence')"],
            engine="docker",
            engine_executable="docker",
            image="python:3.12-slim",
            container_name="egoagent-test",
            container_workdir="/workspace",
            host_env=os.environ.copy(),
            security={
                "network": "none",
                "read_only_root": True,
                "workspace_access": "rw",
                "pids_limit": 256,
                "memory": "512m",
                "cpus": 1.0,
                "pull_policy": "never",
                "user": None,
                "gpus": None,
            },
        )
        graph = {
            "start": "run",
            "nodes": {
                "run": {
                    "op": "进程",
                    "backend": "container",
                    "container": {"image": "python:3.12-slim"},
                    "command": "python",
                    "args": ["experiment.py"],
                    "output_var": "execution",
                    "edges": [{"condition": "process_succeeded", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.execution"}, "edges": []},
            },
        }
        cleanup = {"attempted": True, "removed": True, "exit_code": 0, "detail": ""}

        with patch("pipeline_engine.build_container_invocation", return_value=invocation), patch(
            "pipeline_engine.cleanup_container", return_value=cleanup
        ):
            _, result = self.run_graph(graph)

        self.assertEqual(result.result["backend"], "container")
        self.assertEqual(result.result["command"], ["python", "experiment.py"])
        self.assertIn("isolated-evidence", result.result["stdout"])
        self.assertEqual(result.result["container"]["image"], "python:3.12-slim")
        self.assertTrue(result.result["container"]["cleanup"]["removed"])

    def test_container_timeout_force_cleans_named_container(self):
        invocation = ContainerInvocation(
            argv=[sys.executable, "-c", "import time; time.sleep(10)"],
            engine="docker",
            engine_executable="docker",
            image="python:3.12-slim",
            container_name="egoagent-timeout-test",
            container_workdir="/workspace",
            host_env=os.environ.copy(),
            security={"network": "none"},
        )
        graph = {
            "start": "run",
            "nodes": {
                "run": {
                    "op": "进程",
                    "backend": "container",
                    "container": {"image": "python:3.12-slim"},
                    "command": "python",
                    "args": ["sleep.py"],
                    "timeout_seconds": 0.1,
                    "output_var": "execution",
                    "edges": [{"condition": "timeout", "to": "done"}],
                },
                "done": {
                    "op": "结束",
                    "inputs": {"value": "$ctx.execution.container.cleanup.removed"},
                    "edges": [],
                },
            },
        }
        cleanup = {"attempted": True, "removed": True, "exit_code": 0, "detail": ""}

        with patch("pipeline_engine.build_container_invocation", return_value=invocation), patch(
            "pipeline_engine.cleanup_container", return_value=cleanup
        ) as cleanup_mock:
            _, result = self.run_graph(graph)

        self.assertTrue(result.result)
        cleanup_mock.assert_called_once()

    def test_process_timeout_preserves_stderr_route_data(self):
        graph = {
            "start": "run",
            "nodes": {
                "run": {
                    "op": "进程",
                    "command": "$ctx.python",
                    "args": ["-c", "import time; time.sleep(1)"],
                    "timeout_seconds": 0.05,
                    "output_var": "execution",
                    "edges": [{"condition": "timeout", "to": "timed_out"}],
                },
                "timed_out": {"op": "结束", "inputs": {"value": "$ctx.execution.timed_out"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"python": sys.executable})

        self.assertTrue(result.result)

    def test_process_timeout_terminates_descendant_tree(self):
        leak_file = self.root / "descendant-leak.txt"
        child = (
            "import time; from pathlib import Path; time.sleep(0.8); "
            "Path('descendant-leak.txt').write_text('leaked', encoding='utf-8')"
        )
        parent = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "time.sleep(10)"
        )
        graph = {
            "start": "run",
            "nodes": {
                "run": {
                    "op": "进程",
                    "command": "$ctx.python",
                    "args": ["-c", parent],
                    "timeout_seconds": 0.2,
                    "termination_grace_seconds": 0.1,
                    "output_var": "execution",
                    "edges": [{"condition": "timeout", "to": "timed_out"}],
                },
                "timed_out": {
                    "op": "结束",
                    "inputs": {"value": "$ctx.execution"},
                    "edges": [],
                },
            },
        }

        _, result = self.run_graph(graph, initial_data={"python": sys.executable})
        time.sleep(1.0)

        self.assertTrue(result.result["timed_out"])
        self.assertIsNotNone(result.result["termination_strategy"])
        self.assertFalse(leak_file.exists(), "timed-out Process left a descendant running")

    def test_workspace_snapshot_restore_is_recoverable(self):
        graph = {
            "start": "write_original",
            "nodes": {
                "write_original": {
                    "op": "进程", "command": "$ctx.python",
                    "args": ["-c", "from pathlib import Path; Path('state.txt').write_text('original', encoding='utf-8')"],
                    "edges": [{"condition": "process_succeeded", "to": "snapshot"}],
                },
                "snapshot": {
                    "op": "工作区", "action": "snapshot", "paths": ["state.txt"], "label": "original",
                    "output_var": "snapshot", "edges": [{"condition": "workspace_snapshotted", "to": "overwrite"}],
                },
                "overwrite": {
                    "op": "进程", "command": "$ctx.python",
                    "args": ["-c", "from pathlib import Path; Path('state.txt').write_text('changed', encoding='utf-8')"],
                    "edges": [{"condition": "process_succeeded", "to": "restore"}],
                },
                "restore": {
                    "op": "工作区", "action": "restore", "path": "$ctx.snapshot.path", "backup_before_restore": True,
                    "output_var": "restore", "edges": [{"condition": "workspace_restored", "to": "read"}],
                },
                "read": {
                    "op": "进程", "command": "$ctx.python",
                    "args": ["-c", "from pathlib import Path; print(Path('state.txt').read_text(encoding='utf-8'))"],
                    "output_var": "read_result", "edges": [{"condition": "process_succeeded", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.read_result.stdout"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"python": sys.executable})

        self.assertEqual(result.result.strip(), "original")
        self.assertTrue(result.data["restore"]["backup_path"])
        self.assertEqual(result.data["restore"]["count"], 1)

    def test_workspace_reads_bounded_text_json_and_typed_missing_defaults(self):
        (self.root / "experiment.py").write_text("VALUE = 3\n", encoding="utf-8")
        (self.root / "prompt.json").write_text('{"task_description":"demo"}', encoding="utf-8")
        graph = {
            "start": "code",
            "nodes": {
                "code": {
                    "op": "工作区", "action": "read_text", "path": "experiment.py",
                    "outputs": {"text": "code"},
                    "edges": [{"condition": "workspace_read", "to": "prompt"}],
                },
                "prompt": {
                    "op": "工作区", "action": "read_json", "path": "prompt.json",
                    "outputs": {"structured": "prompt"},
                    "edges": [{"condition": "workspace_read", "to": "missing"}],
                },
                "missing": {
                    "op": "工作区", "action": "read_json", "path": "seed_ideas.json",
                    "allow_missing": True, "default": [], "outputs": {"structured": "seeds"},
                    "edges": [{"condition": "workspace_missing", "to": "done"}],
                },
                "done": {
                    "op": "结束",
                    "value": {"code": "$ctx.code", "task": "$ctx.prompt.task_description", "seeds": "$ctx.seeds"},
                    "edges": [],
                },
            },
        }

        _, result = self.run_graph(graph)

        self.assertEqual(result.result["code"].splitlines(), ["VALUE = 3"])
        self.assertEqual(result.result["task"], "demo")
        self.assertEqual(result.result["seeds"], [])

    def test_workspace_atomically_writes_text_and_json_with_typed_results(self):
        graph = {
            "start": "paper",
            "nodes": {
                "paper": {
                    "op": "工作区", "action": "write_text", "path": "reports/paper.md",
                    "value": "$ctx.draft", "overwrite": True, "track_change": True,
                    "edges": [{"condition": "workspace_written", "to": "metadata"}],
                },
                "metadata": {
                    "op": "工作区", "action": "write_json", "path": "reports/metadata.json",
                    "value": {"accepted": True, "score": 8}, "overwrite": True,
                    "outputs": {"structured": "metadata"},
                    "edges": [{"condition": "workspace_written", "to": "done"}],
                },
                "done": {
                    "op": "结束",
                    "value": {"paper": "$node.paper.path", "metadata": "$ctx.metadata"},
                    "edges": [],
                },
            },
        }

        _, result = self.run_graph(graph, initial_data={"draft": "# Evidence\nmetric=0.8\n"})

        self.assertEqual(result.result["paper"], "reports/paper.md")
        self.assertEqual(result.result["metadata"], {"accepted": True, "score": 8})
        self.assertEqual((self.root / "reports" / "paper.md").read_text(encoding="utf-8").splitlines(), ["# Evidence", "metric=0.8"])
        self.assertEqual(json.loads((self.root / "reports" / "metadata.json").read_text(encoding="utf-8")), {"accepted": True, "score": 8})

    def test_workspace_binary_write_is_readable_and_reviewable(self):
        from harness_editor.change_tracker import get_changes, reject_change, undo_change

        graph = {
            "start": "write",
            "nodes": {
                "write": {
                    "op": "工作区", "action": "write_binary", "path": "assets/pixel.bin",
                    "value": "AAEC/w==", "binary_encoding": "base64", "overwrite": True,
                    "edges": [{"condition": "workspace_written", "to": "read"}],
                },
                "read": {
                    "op": "工作区", "action": "read_binary", "path": "assets/pixel.bin",
                    "outputs": {"data": "encoded"},
                    "edges": [{"condition": "workspace_read", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.encoded"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, "AAEC/w==")
        self.assertEqual((self.root / "assets" / "pixel.bin").read_bytes(), b"\x00\x01\x02\xff")
        change = get_changes()[0]
        self.assertEqual(change["change_type"], "binary")
        self.assertFalse(reject_change(change["id"], hunk_id=change["hunks"][0]["id"]))
        self.assertTrue(reject_change(change["id"], hunk_id=change["hunks"][0]["id"], confirm_delete=True))
        self.assertFalse((self.root / "assets" / "pixel.bin").exists())
        self.assertTrue(undo_change(change["id"], change["hunks"][0]["id"]))
        self.assertEqual((self.root / "assets" / "pixel.bin").read_bytes(), b"\x00\x01\x02\xff")

    def test_workspace_move_and_delete_are_tracked_and_reversible(self):
        from harness_editor.change_tracker import clear_changes, get_changes, reject_change

        source = self.root / "old.txt"
        source.write_text("move me\n", encoding="utf-8")
        move_graph = {
            "start": "move",
            "nodes": {
                "move": {
                    "op": "工作区", "action": "move", "source": "old.txt", "target": "renamed/new.txt",
                    "edges": [{"condition": "workspace_moved", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.move", "edges": []},
            },
        }
        self.run_graph(move_graph)
        move_change = get_changes()[0]
        self.assertEqual(move_change["change_type"], "move")
        self.assertTrue(reject_change(move_change["id"], hunk_id=move_change["hunks"][0]["id"]))
        self.assertEqual(source.read_text(encoding="utf-8"), "move me\n")

        clear_changes()
        delete_graph = {
            "start": "delete",
            "nodes": {
                "delete": {
                    "op": "工作区", "action": "delete", "path": "old.txt",
                    "edges": [{"condition": "workspace_deleted", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.delete", "edges": []},
            },
        }
        self.run_graph(delete_graph)
        delete_change = get_changes()[0]
        self.assertTrue(delete_change["is_deleted_file"])
        self.assertEqual("".join(delete_change["hunks"][0]["old_lines"]).replace("\r\n", "\n"), "move me\n")
        self.assertTrue(reject_change(delete_change["id"], hunk_id=delete_change["hunks"][0]["id"]))
        self.assertEqual(source.read_text(encoding="utf-8"), "move me\n")

    def test_event_log_is_ordered_and_replayable(self):
        graph = {
            "start": "save",
            "event_log": {"path": ".egoagent/events/{run_id}.jsonl"},
            "nodes": {
                "save": {
                    "op": "数据", "action": "set", "key": "answer", "value": 42,
                    "edges": [{"condition": "default", "to": "replay"}],
                },
                "replay": {
                    "op": "检查点", "action": "replay", "path": "$ctx._event_log_path",
                    "output_var": "events", "edges": [{"condition": "events_replayed", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.events"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph)

        sequences = [event["sequence"] for event in result.result]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertIn("node_enter", [event["event"] for event in result.result])
        self.assertTrue((self.root / result.data["_event_log_path"]).is_file())

    def test_checkpoint_resume_starts_at_exact_next_node(self):
        graph = {
            "start": "write_once",
            "event_log": True,
            "nodes": {
                "write_once": {
                    "op": "进程", "command": "$ctx.python",
                    "args": ["-c", "from pathlib import Path; p=Path('marker.txt'); p.write_text(p.read_text(encoding='utf-8')+'x' if p.exists() else 'x', encoding='utf-8')"],
                    "edges": [{"condition": "process_succeeded", "to": "checkpoint"}],
                },
                "checkpoint": {
                    "op": "检查点", "action": "save", "label": "resume-test",
                    "edges": [{"condition": "checkpoint_saved", "to": "read"}],
                },
                "read": {
                    "op": "进程", "command": "$ctx.python",
                    "args": ["-c", "from pathlib import Path; print(Path('marker.txt').read_text(encoding='utf-8'))"],
                    "output_var": "read_result", "edges": [{"condition": "process_succeeded", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.read_result.stdout"}, "edges": []},
            },
        }
        first_harness, first = self.run_graph(graph, initial_data={"python": sys.executable})
        checkpoint = first.node_outputs["checkpoint"]["path"]
        original_run_id = first.run_id

        resumed_harness = FakeHarness(self.root, graph)
        resumed = PipelineRunner(
            resumed_harness,
            initial_data={"python": sys.executable},
            resume_from=checkpoint,
        ).run()

        self.assertEqual((self.root / "marker.txt").read_text(encoding="utf-8"), "x")
        self.assertEqual(resumed.result.strip(), "x")
        self.assertEqual(resumed.run_id, original_run_id)
        self.assertEqual(resumed.data["_resumed_from"], Path(checkpoint).resolve().relative_to(self.root).as_posix())

    def test_agent_edit_transaction_rejects_pending_hunks_and_restores_file(self):
        from harness_editor.change_tracker import clear_changes, get_active_transaction, record_change

        clear_changes()
        target = self.root / "demo.txt"
        target.write_text("old\nkeep\n", encoding="utf-8")

        class EditingAgent(FakeAgent):
            def step(agent_self, messages, tools_desc=None, on_token=None):
                old = target.read_text(encoding="utf-8")
                new = "new\nkeep\n"
                target.write_text(new, encoding="utf-8")
                record_change(target, old, new, "patch_file")
                self.assertIsNotNone(get_active_transaction())
                return super().step(messages, tools_desc=tools_desc, on_token=on_token)

        graph = {
            "start": "begin",
            "nodes": {
                "begin": {
                    "op": "工作区", "action": "begin_transaction", "paths": ["demo.txt"],
                    "edges": [{"condition": "transaction_started", "to": "edit"}],
                },
                "edit": {
                    "op": "Agent", "agent": "editor", "tools": "none",
                    "edges": [{"condition": "has_text", "to": "review"}],
                },
                "review": {
                    "op": "工作区", "action": "review_transaction", "pending_policy": "reject",
                    "output_var": "review", "edges": [{"condition": "changes_rejected", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.review"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, agents={"editor": EditingAgent("editor", ["edited"])})

        self.assertEqual(result.result["status"], "rejected")
        self.assertEqual(result.result["pending"], 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "old\nkeep\n")
        self.assertIsNone(get_active_transaction())

    def test_validated_runtime_generated_subflow_preserves_typed_result(self):
        inline = {
            "start": "copy",
            "nodes": {
                "copy": {
                    "op": "数据", "action": "set", "key": "answer", "value": "$ctx.number",
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": {"answer": "$ctx.answer"}}, "edges": []},
            },
        }
        graph = {
            "start": "dynamic",
            "nodes": {
                "dynamic": {
                    "op": "子流程", "inline_pipeline": inline, "result_mode": "result",
                    "inputs": {"data": {"number": "$ctx.number"}}, "output_var": "child",
                    "edges": [{"condition": "subflow_done", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.child"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"number": 7})

        self.assertEqual(result.result, {"answer": 7})

    def test_runtime_generated_subflow_rejects_unsafe_nodes_by_default(self):
        graph = {
            "start": "dynamic",
            "nodes": {
                "dynamic": {
                    "op": "子流程",
                    "inline_pipeline": {"start": "script", "nodes": {"script": {"op": "Python", "script": "x", "edges": []}}},
                    "edges": [{"condition": "error", "to": "blocked"}],
                },
                "blocked": {"op": "结束", "inputs": {"value": "$ctx._error.message"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph)

        self.assertIn("unsafe operations", result.result)

    def test_port_graph_subflow_runs_typed_tasks_through_identity_ego_harness(self):
        graph = {
            "start": "blocks",
            "nodes": {
                "blocks": {
                    "op": "子流程",
                    "mode": "port_graph",
                    "block_harness": "bounded_action_worker",
                    "agent_map": {"actor": "agent"},
                    "inputs": {
                        "data": {"request": "prepare artifacts"},
                        "port_graph": [
                            {
                                "id": "T1", "instruction": "prepare first", "inputs": {},
                                "dependencies": [], "sensitive": False,
                                "output_schema": {"type": "object", "required": ["artifact"]},
                            },
                            {
                                "id": "T2", "instruction": "use first", "inputs": {"source": "T1"},
                                "dependencies": ["T1"], "sensitive": False,
                                "output_schema": {"type": "string", "minLength": 1},
                            },
                        ],
                    },
                    "edges": [{"condition": "subflow_done", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.block_results"}, "edges": []},
            },
        }
        agent = FakeAgent("agent", ['{"artifact":"first"}', "dependent result"])

        _, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual([item["task_id"] for item in result.result], ["T1", "T2"])
        self.assertEqual([item["status"] for item in result.result], ["completed", "completed"])
        self.assertEqual(result.result[0]["output"], {"artifact": "first"})
        self.assertEqual(result.result[1]["inputs"], {"source": {"artifact": "first"}})
        self.assertEqual(result.data["port_graph_result"]["status"], "completed")
        self.assertEqual(agent.calls, 2)

    def test_port_graph_subflow_rejects_sensitive_task_without_running_agent(self):
        graph = {
            "start": "blocks",
            "nodes": {
                "blocks": {
                    "op": "子流程", "mode": "port_graph",
                    "block_harness": "bounded_action_worker", "agent_map": {"actor": "agent"},
                    "inputs": {"port_graph": [{
                        "id": "send", "instruction": "send message", "inputs": {},
                        "dependencies": [], "sensitive": True, "output_schema": {"type": "string"},
                    }]},
                    "edges": [{"condition": "subflow_done", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.block_results"}, "edges": []},
            },
        }
        agent = FakeAgent("agent", ["must not run"])

        _, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.result[0]["status"], "rejected")
        self.assertEqual(agent.calls, 0)

    def test_retry_and_structured_output_validation(self):
        agent = FakeAgent()
        agent.llm = FakeLLM(["not-json", '{"ok": true}'])
        graph = {
            "start": "model",
            "max_steps": 4,
            "nodes": {
                "model": {
                    "op": "模型",
                    "prompt": "test",
                    "parse_as": "json",
                    "retry": {"max_attempts": 2},
                    "output_schema": {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$node.model.structured"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph, agents={"agent": agent})
        self.assertEqual(result.result, {"ok": True})
        self.assertEqual(result.stats.retries, 1)
        self.assertEqual(agent.llm.calls, 2)

    def test_model_json_object_extracts_a_verdict_from_surrounding_prose(self):
        agent = FakeAgent()
        agent.llm = FakeLLM(['Verdict follows:\n```json\n{"complete": true, "score": 1, "missing": ""}\n```'])
        graph = {
            "start": "judge",
            "nodes": {
                "judge": {
                    "op": "模型", "prompt": "test", "parse_as": "json_object",
                    "output_schema": {
                        "type": "object", "required": ["complete", "score", "missing"],
                        "properties": {
                            "complete": {"type": "boolean"}, "score": {"type": "number"},
                            "missing": {"type": "string"},
                        },
                    },
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.judge.structured", "edges": []},
            },
        }

        _, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.result, {"complete": True, "score": 1, "missing": ""})
        self.assertFalse(result.node_outputs["judge"]["parse_fallback"])

    def test_model_json_fallback_is_conservative_and_does_not_retry(self):
        agent = FakeAgent()
        agent.llm = FakeLLM(["not a JSON verdict"])
        fallback = {
            "complete": False,
            "score": 0.0,
            "missing": "Judge verdict could not be parsed.",
        }
        graph = {
            "start": "judge",
            "nodes": {
                "judge": {
                    "op": "模型", "prompt": "test", "parse_as": "json_object",
                    "json_fallback": fallback, "retry": {"max_attempts": 1},
                    "output_schema": {
                        "type": "object", "required": ["complete", "score", "missing"],
                        "properties": {
                            "complete": {"type": "boolean"}, "score": {"type": "number"},
                            "missing": {"type": "string"},
                        },
                    },
                    "edges": [{"condition": "has_text", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.judge.structured", "edges": []},
            },
        }
        events = []

        _, result = self.run_graph(graph, agents={"agent": agent}, events=events)

        self.assertEqual(result.result, fallback)
        self.assertTrue(result.node_outputs["judge"]["parse_fallback"])
        self.assertEqual(agent.llm.calls, 1)
        self.assertTrue(any(event == "model_json_fallback" for event, _ in events))

    def test_error_edge_handles_retry_exhaustion(self):
        graph = {
            "start": "model",
            "nodes": {
                "model": {
                    "op": "模型",
                    "prompt": "test",
                    "parse_as": "json",
                    "retry": 1,
                    "edges": [{"condition": "error", "to": "fallback"}],
                },
                "fallback": {"op": "结束", "value": "fallback", "edges": []},
            },
        }
        agent = FakeAgent()
        agent.llm = FakeLLM(["bad", "still bad"])
        _, result = self.run_graph(graph, agents={"agent": agent})
        self.assertEqual(result.result, "fallback")
        self.assertIn("_error", result.data)

    def test_parallel_branches_join_deterministically(self):
        graph = {
            "start": "parallel",
            "nodes": {
                "parallel": {
                    "op": "并行",
                    "branches": [{"name": "a", "start": "a"}, {"name": "b", "start": "b"}],
                    "join": "join",
                    "edges": [],
                },
                "a": {"op": "数据", "action": "set", "key": "branch", "value": "A", "edges": [{"condition": "default", "to": "join"}]},
                "b": {"op": "数据", "action": "set", "key": "branch", "value": "B", "edges": [{"condition": "default", "to": "join"}]},
                "join": {"op": "合并", "strategy": "list", "source": "$ctx.parallel_results", "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.join.value"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual([item["name"] for item in result.result], ["a", "b"])
        self.assertEqual([item["data"]["branch"] for item in result.result], ["A", "B"])

    def test_parallel_map_fans_out_dynamic_items(self):
        graph = {
            "start": "map",
            "nodes": {
                "map": {
                    "op": "映射",
                    "source": "$ctx.items",
                    "item_var": "item",
                    "body_start": "read_item",
                    "join": "join",
                    "output_var": "mapped",
                    "edges": [],
                },
                "read_item": {"op": "数据", "action": "get", "key": "item", "edges": [{"condition": "default", "to": "join"}]},
                "join": {"op": "合并", "source": "$ctx.mapped", "strategy": "list", "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.join.value"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph, initial_data={"items": ["alpha", "beta", "gamma"]})
        self.assertEqual([item["last"]["value"] for item in result.result], ["alpha", "beta", "gamma"])

    def test_data_topological_levels_preserves_stable_parallel_waves(self):
        graph = {
            "start": "levels",
            "nodes": {
                "levels": {
                    "op": "数据", "action": "topological_levels", "key": "levels",
                    "source": "$ctx.tasks", "edges": [{"condition": "topology_ready", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.levels"}, "edges": []},
            },
        }
        tasks = [
            {"id": "A", "dependencies": []},
            {"id": "B", "dependencies": ["A"]},
            {"id": "C", "dependencies": []},
            {"id": "D", "dependencies": ["B", "C"]},
        ]

        _, result = self.run_graph(graph, initial_data={"tasks": tasks})

        self.assertEqual([[item["id"] for item in level] for level in result.result], [["A", "C"], ["B"], ["D"]])

    def test_data_topological_levels_rejects_cycles(self):
        graph = {
            "start": "levels",
            "nodes": {
                "levels": {
                    "op": "数据", "action": "topological_levels", "key": "levels",
                    "source": "$ctx.tasks", "edges": [{"condition": "error", "to": "blocked"}],
                },
                "blocked": {"op": "结束", "inputs": {"value": "$ctx._error.message"}, "edges": []},
            },
        }

        _, result = self.run_graph(
            graph,
            initial_data={"tasks": [{"id": "A", "dependencies": ["B"]}, {"id": "B", "dependencies": ["A"]}]},
        )

        self.assertIn("dependency cycle", result.result)

    def test_data_validate_schema_routes_valid_and_invalid_values(self):
        graph = {
            "start": "validate",
            "nodes": {
                "validate": {
                    "op": "数据", "action": "validate_schema", "key": "validation",
                    "source": "$ctx.candidate", "schema": "$ctx.schema",
                    "edges": [
                        {"condition": "schema_valid", "to": "valid"},
                        {"condition": "schema_invalid", "to": "invalid"},
                    ],
                },
                "valid": {"op": "结束", "value": "valid", "edges": []},
                "invalid": {"op": "结束", "inputs": {"value": "$ctx.validation"}, "edges": []},
            },
        }
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}

        _, valid = self.run_graph(graph, initial_data={"candidate": {"answer": "yes"}, "schema": schema})
        _, invalid = self.run_graph(graph, initial_data={"candidate": {"answer": 3}, "schema": schema})

        self.assertEqual(valid.result, "valid")
        self.assertFalse(invalid.result["valid"])
        self.assertIn("$value.answer must be string", invalid.result["errors"][0])

    def test_state_transition_commits_atomically_and_rejects_stale_or_impossible_actions(self):
        schema = {
            "type": "object", "additionalProperties": False,
            "required": ["_revision", "actors", "events"],
            "properties": {
                "_revision": {"type": "integer", "minimum": 0},
                "actors": {"type": "object"},
                "events": {"type": "array"},
            },
        }
        graph = {
            "start": "commit",
            "nodes": {
                "commit": {
                    "op": "数据", "action": "state_transition", "key": "game",
                    "inputs": {"transition": "$ctx.transition"}, "schema": schema,
                    "output_var": "commit_result",
                    "edges": [
                        {"condition": "transition_committed", "to": "done"},
                        {"condition": "transition_rejected", "to": "done"},
                    ],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.commit_result"}, "edges": []},
            },
        }
        initial_state = {
            "_revision": 4,
            "actors": {"iris": {"inventory": [], "ammo": 0}},
            "events": [],
        }
        valid = {
            "expected_revision": 4,
            "preconditions": [
                {"path": "actors.iris.ammo", "operator": "gte", "value": 0},
            ],
            "operations": [
                {"op": "append", "path": "actors.iris.inventory", "value": "revolver"},
                {"op": "set", "path": "actors.iris.ammo", "value": 6},
                {"op": "append", "path": "events", "value": {"type": "item_acquired"}},
            ],
        }
        _, committed = self.run_graph(
            graph, initial_data={"game": copy.deepcopy(initial_state), "transition": valid},
        )
        self.assertTrue(committed.result["accepted"])
        self.assertEqual(committed.result["revision"], 5)
        self.assertEqual(committed.result["state"]["actors"]["iris"]["ammo"], 6)

        impossible = {
            "expected_revision": 4,
            "preconditions": [
                {"path": "actors.iris.inventory", "operator": "contains", "value": "revolver", "reason": "missing_item"},
                {"path": "actors.iris.ammo", "operator": "gt", "value": 0, "reason": "no_ammo"},
            ],
            "operations": [
                {"op": "increment", "path": "actors.iris.ammo", "value": -1},
                {"op": "append", "path": "events", "value": {"type": "shot"}},
            ],
        }
        _, rejected = self.run_graph(
            graph, initial_data={"game": copy.deepcopy(initial_state), "transition": impossible},
        )
        self.assertFalse(rejected.result["accepted"])
        self.assertEqual(rejected.result["revision"], 4)
        self.assertEqual(rejected.result["state"], initial_state)
        self.assertEqual(rejected.result["reason_codes"], ["missing_item", "no_ammo"])

    def test_json_schema_integer_rejects_boolean_and_enforces_collection_bounds(self):
        graph = {
            "start": "validate",
            "nodes": {
                "validate": {
                    "op": "数据", "action": "validate_schema", "key": "validation",
                    "source": "$ctx.candidate",
                    "schema": {
                        "type": "object", "additionalProperties": False,
                        "required": ["count", "items"],
                        "properties": {
                            "count": {"type": "integer", "minimum": 1},
                            "items": {"type": "array", "minItems": 1, "maxItems": 2},
                        },
                    },
                    "edges": [{"condition": "schema_invalid", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.validation.errors"}, "edges": []},
            },
        }

        _, result = self.run_graph(
            graph,
            initial_data={"candidate": {"count": True, "items": [], "extra": "no"}},
        )

        self.assertTrue(any("count must be integer" in error for error in result.result))
        self.assertTrue(any("items has fewer than minItems" in error for error in result.result))
        self.assertTrue(any("extra is not allowed" in error for error in result.result))

    def test_loop_can_break_early_without_leaking_stack_state(self):
        graph = {
            "start": "loop",
            "context": {"items": [1, 2, 3], "done": False},
            "nodes": {
                "loop": {"op": "循环", "list_var": "items", "item_var": "item", "body_start": "mark", "break_when": "ctx.done", "edges": [{"condition": "loop_break", "to": "output"}, {"condition": "loop_done", "to": "failed"}]},
                "mark": {"op": "数据", "action": "set", "key": "done", "value": True, "edges": [{"condition": "default", "to": "loop"}]},
                "output": {"op": "结束", "inputs": {"value": "$ctx.item"}, "edges": []},
                "failed": {"op": "结束", "value": "failed", "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, 1)
        self.assertEqual(result.data["_loop_stack"], [])

    def test_parallel_reducers_merge_branch_local_state(self):
        graph = {
            "start": "parallel",
            "context": {"notes": ["seed"]},
            "reducers": {"notes": "append"},
            "nodes": {
                "parallel": {
                    "op": "并行",
                    "branches": [{"name": "a", "start": "a"}, {"name": "b", "start": "b"}],
                    "join": "done",
                    "edges": [],
                },
                "a": {"op": "数据", "action": "append", "key": "notes", "value": "A", "edges": [{"condition": "default", "to": "done"}]},
                "b": {"op": "数据", "action": "append", "key": "notes", "value": "B", "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx.notes"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, ["seed", "A", "B"])

    def test_model_node_selects_identity_and_includes_ego_prompt(self):
        planner = FakeAgent("planner", ['{"tasks": ["one"]}'])
        writer = FakeAgent("writer", ["unused"])
        graph = {
            "start": "plan",
            "nodes": {
                "plan": {"op": "模型", "agent": "planner", "prompt": "test", "parse_as": "json", "edges": [{"condition": "has_text", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.plan.value"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph, agents={"planner": planner, "writer": writer}, initial_data={"value": "topic"})
        self.assertEqual(result.result, {"tasks": ["one"]})
        self.assertEqual(planner.llm.calls, 1)
        self.assertEqual(writer.llm.calls, 0)
        self.assertEqual(planner.llm.last_messages[0]["content"], "identity:planner; tools:False")

    def test_context_node_selects_and_compacts_history(self):
        summarizer = FakeAgent("summarizer", ["durable memory"])
        graph = {
            "start": "compact",
            "nodes": {
                "compact": {"op": "上下文", "agent": "summarizer", "action": "compact", "keep_last": 1, "last_n": 10, "edges": [{"condition": "context_ready", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.compact.messages"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph, agents={"summarizer": summarizer})
        harness.prompts["context"] = "{history}"
        harness.session.messages = [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
        ]
        result = PipelineRunner(harness).run()
        self.assertEqual(result.result[0]["name"], "context_summary")
        self.assertEqual(result.result[0]["content"], "durable memory")
        self.assertEqual(result.result[-1]["content"], "current")

    def test_persistent_memory_retrieval_and_reflection_trigger(self):
        graph = {
            "start": "add_one",
            "nodes": {
                "add_one": {"op": "记忆", "action": "add", "namespace": "agent", "memory_type": "skill", "value": "automatic plant watering sensor", "importance": 7, "edges": [{"condition": "memory_added", "to": "add_two"}]},
                "add_two": {"op": "记忆", "action": "add", "namespace": "agent", "memory_type": "event", "value": "soil became dry", "importance": 3, "edges": [{"condition": "memory_added", "to": "due"}]},
                "due": {"op": "记忆", "action": "needs_reflection", "namespace": "agent", "threshold": 10, "outputs": {"value": "before_reflection"}, "edges": [{"condition": "reflection_due", "to": "mark"}]},
                "mark": {"op": "记忆", "action": "mark_reflected", "namespace": "agent", "edges": [{"condition": "reflection_marked", "to": "after"}]},
                "after": {"op": "记忆", "action": "needs_reflection", "namespace": "agent", "threshold": 10, "outputs": {"value": "after_reflection"}, "edges": [{"condition": "reflection_not_due", "to": "search"}]},
                "search": {"op": "记忆", "action": "search", "namespace": "agent", "memory_type": "skill", "query": "plant water sensor", "top_k": 1, "edges": [{"condition": "memory_found", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.search.items"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertTrue(result.data["before_reflection"]["due"])
        self.assertFalse(result.data["after_reflection"]["due"])
        self.assertEqual(result.result[0]["type"], "skill")
        self.assertIn("plant watering", result.result[0]["text"])
        self.assertTrue((self.root / ".egoagent/memory/agent.json").is_file())

    def test_memory_unique_recent_window_and_skill_upsert(self):
        graph = {
            "start": "event_one",
            "nodes": {
                "event_one": {"op": "记忆", "action": "add_unique", "namespace": "dedupe", "memory_type": "event", "value": {"text": "waves", "metadata": {"event_key": "ocean"}}, "dedupe_key": "metadata.event_key", "retention": 5, "edges": [{"condition": "memory_added", "to": "event_two"}]},
                "event_two": {"op": "记忆", "action": "add_unique", "namespace": "dedupe", "memory_type": "event", "value": {"text": "same waves", "metadata": {"event_key": "ocean"}}, "dedupe_key": "metadata.event_key", "retention": 5, "edges": [{"condition": "memory_duplicate", "to": "skill_one"}]},
                "skill_one": {"op": "记忆", "action": "upsert", "namespace": "dedupe", "memory_type": "skill", "value": {"id": "mine_wood", "text": "old procedure"}, "edges": [{"condition": "memory_added", "to": "skill_two"}]},
                "skill_two": {"op": "记忆", "action": "upsert", "namespace": "dedupe", "memory_type": "skill", "value": {"id": "mine_wood", "text": "improved procedure"}, "edges": [{"condition": "memory_updated", "to": "list"}]},
                "list": {"op": "记忆", "action": "list", "namespace": "dedupe", "top_k": 10, "outputs": {"value": "all_memory"}, "edges": [{"condition": "memory_found", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx.all_memory"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(len(result.result), 2)
        self.assertEqual([item["text"] for item in result.result], ["waves", "improved procedure"])

    def test_tool_node_can_execute_independent_calls_in_parallel(self):
        calls = [
            {"id": "1", "function": {"name": "first", "arguments": "{}"}},
            {"id": "2", "function": {"name": "second", "arguments": "{}"}},
        ]
        graph = {
            "start": "tools",
            "budget": {"max_tool_calls": 3},
            "nodes": {
                "tools": {"op": "工具", "agent": "agent", "parallel": True, "inputs": {"tool_calls": calls}, "edges": [{"condition": "tools_executed", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$node.tools.results"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual([item["name"] for item in result.result], ["first", "second"])
        self.assertEqual(result.stats.tool_calls, 2)

    def test_timeout_can_follow_timeout_edge(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "slow.py").write_text("import time\ndef run(ctx):\n    time.sleep(0.2)\n    return {'value': 'late'}\n", encoding="utf-8")
        graph = {
            "start": "slow",
            "nodes": {
                "slow": {"op": "Python", "script": "slow", "timeout_seconds": 0.01, "edges": [{"condition": "timeout", "to": "fallback"}]},
                "fallback": {"op": "结束", "value": "timed-out", "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, "timed-out")

    def test_file_data_and_checkpoint_are_workspace_confined(self):
        graph = {
            "start": "save",
            "checkpoint_dir": ".egoagent/checkpoints",
            "nodes": {
                "save": {"op": "保存数据", "scope": "file", "path": ".egoagent/state.json", "key": "answer", "value": 42, "edges": [{"condition": "default", "to": "load"}]},
                "load": {"op": "读取数据", "scope": "file", "path": ".egoagent/state.json", "key": "answer", "output_var": "loaded", "edges": [{"condition": "default", "to": "checkpoint"}]},
                "checkpoint": {"op": "检查点", "label": "state", "edges": [{"condition": "default", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$ctx.loaded"}, "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, 42)
        self.assertEqual(json.loads((self.root / ".egoagent/state.json").read_text())["answer"], 42)
        self.assertEqual(len(list((self.root / ".egoagent/checkpoints").glob("*.json"))), 1)

    def test_noninteractive_approval_uses_explicit_default(self):
        graph = {
            "start": "approval",
            "nodes": {
                "approval": {"op": "人工审批", "default": "approved", "edges": [{"condition": "approved", "to": "done"}]},
                "done": {"op": "结束", "value": "ok", "edges": []},
            },
        }
        _, result = self.run_graph(graph)
        self.assertEqual(result.result, "ok")

    def test_approval_passes_through_or_edits_reviewed_data(self):
        graph = {
            "start": "approval",
            "nodes": {
                "approval": {
                    "op": "人工审批",
                    "data": "$ctx.proposal",
                    "editable": True,
                    "outputs": {
                        "approved_data": "reviewed",
                        "review_message": "review_message",
                    },
                    "edges": [{"condition": "approved", "to": "done"}],
                },
                "done": {"op": "结束", "inputs": {"value": "$ctx.reviewed"}, "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness._non_interactive = False
        runner = PipelineRunner(
            harness,
            get_input=lambda: {
                "decision": "approved",
                "data": {"command": "safe-command", "reviewed": True},
                "message": "parameters corrected",
            },
            initial_data={"proposal": {"command": "unsafe-command"}},
        )

        result = runner.run()

        self.assertEqual(result.result, {"command": "safe-command", "reviewed": True})
        self.assertEqual(result.data["approval"]["message"], "parameters corrected")
        self.assertEqual(result.data["review_message"], "parameters corrected")

    def test_thought_action_parser_executes_only_the_last_fenced_action(self):
        class RecordingAgent(FakeAgent):
            def __init__(self):
                super().__init__()
                self.executed = []

            def execute_tool_call(self, call):
                self.executed.append(copy.deepcopy(call))
                return "command completed"

        agent = RecordingAgent()
        graph = {
            "start": "parse",
            "nodes": {
                "parse": {
                    "op": "文本处理",
                    "mode": "thought_action",
                    "inputs": {"text": "$ctx.response"},
                    "action_tool": "run_command",
                    "action_argument": "command",
                    "action_arguments": {"blocking": True},
                    "edges": [{"condition": "has_tool_calls", "to": "execute"}],
                },
                "execute": {
                    "op": "工具",
                    "agent": "agent",
                    "edges": [{"condition": "tools_executed", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx._trajectory", "edges": []},
            },
        }
        response = "Inspect first.\n```\necho ignored\n```\nNow act.\n```bash\necho chosen\n```"

        _, result = self.run_graph(graph, agents={"agent": agent}, initial_data={"response": response})

        arguments = json.loads(agent.executed[0]["function"]["arguments"])
        self.assertEqual(arguments, {"blocking": True, "command": "echo chosen"})
        self.assertEqual(result.result[0]["environment_action"], "echo chosen")
        self.assertIn("Inspect first", result.result[0]["thought"])
        self.assertEqual(result.result[0]["observation"], "command completed")

    def test_thought_action_format_errors_requery_then_exit_format(self):
        graph = {
            "start": "parse",
            "max_node_steps": 10,
            "nodes": {
                "parse": {
                    "op": "文本处理",
                    "mode": "thought_action",
                    "inputs": {"text": "$ctx.response"},
                    "max_requeries": 3,
                    "edges": [
                        {"condition": "format_error", "to": "parse"},
                        {"condition": "format_error_exhausted", "to": "done"},
                    ],
                },
                "done": {"op": "结束", "value": "$node.parse.value", "edges": []},
            },
        }

        harness, result = self.run_graph(graph, initial_data={"response": "ordinary final prose"})

        self.assertEqual(result.result["exit_status"], "exit_format")
        self.assertEqual(result.result["format_failures"], 3)
        self.assertEqual(len(result.data["_trajectory"]), 3)
        corrections = [
            message for message in harness.session.messages
            if message.get("name") == "runtime_action_format_error"
        ]
        self.assertEqual(len(corrections), 2)

    def test_aider_editblock_parser_extracts_edits_and_shell_commands(self):
        graph = {
            "start": "parse",
            "nodes": {
                "parse": {
                    "op": "文本处理",
                    "mode": "aider_search_replace",
                    "inputs": {"text": "$ctx.response"},
                    "valid_filenames": ["src/demo.py"],
                    "require_edits": True,
                    "edges": [{"condition": "editblocks_parsed", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.parse.value", "edges": []},
            },
        }
        response = """Run the focused check after editing.
```bash
python -m unittest tests.test_demo
```
src/demo.py
```python
<<<<<<< SEARCH
def old():
    return 1
=======
def new():
    return 2
>>>>>>> REPLACE
```
<<<<<<< SEARCH
VALUE = 1
=======
VALUE = 2
>>>>>>> REPLACE
"""

        _, result = self.run_graph(graph, initial_data={"response": response})

        self.assertTrue(result.result["valid"])
        self.assertEqual(len(result.result["edits"]), 2)
        self.assertEqual(result.result["edits"][0]["path"], "src/demo.py")
        self.assertIn("python -m unittest", result.result["shell_commands"][0])

    def test_aider_editblock_parser_requeries_malformed_output_three_times(self):
        graph = {
            "start": "parse",
            "max_node_steps": 10,
            "nodes": {
                "parse": {
                    "op": "文本处理",
                    "mode": "aider_search_replace",
                    "inputs": {"text": "$ctx.response"},
                    "require_edits": True,
                    "max_requeries": 3,
                    "edges": [
                        {"condition": "format_error", "to": "parse"},
                        {"condition": "format_error_exhausted", "to": "done"},
                    ],
                },
                "done": {"op": "结束", "value": "$node.parse.value", "edges": []},
            },
        }

        harness, result = self.run_graph(graph, initial_data={"response": "ordinary prose"})

        self.assertTrue(result.result["exhausted"])
        self.assertEqual(result.result["format_failures"], 3)
        corrections = [
            message for message in harness.session.messages
            if message.get("name") == "runtime_aider_format_error"
        ]
        self.assertEqual(len(corrections), 2)

    def test_workspace_applies_aider_edits_with_whitespace_fallback_and_new_file(self):
        source = self.root / "src" / "demo.py"
        source.parent.mkdir()
        source.write_text("def value():\n    return 1\n", encoding="utf-8")
        graph = {
            "start": "apply",
            "nodes": {
                "apply": {
                    "op": "工作区",
                    "action": "apply_search_replace",
                    "inputs": {"edits": "$ctx.edits"},
                    "allowed_paths": ["src/demo.py"],
                    "atomic": True,
                    "edges": [{"condition": "edits_applied", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.apply.value", "edges": []},
            },
        }
        edits = [
            {"path": "wrong.py", "search": "return 1\n", "replace": "return 2\n"},
            {"path": "created.txt", "search": "", "replace": "created\n"},
        ]

        _, result = self.run_graph(graph, initial_data={"edits": edits})

        self.assertEqual(result.result["status"], "applied")
        self.assertEqual(result.result["applied"], 2)
        self.assertEqual(source.read_text(encoding="utf-8"), "def value():\n    return 2\n")
        self.assertEqual((self.root / "created.txt").read_text(encoding="utf-8"), "created\n")
        self.assertEqual(result.result["edits"][0]["path"], "src/demo.py")

    def test_workspace_aider_edit_preserves_existing_line_endings(self):
        source = self.root / "demo.txt"
        source.write_bytes(b"alpha\nbeta\n")
        graph = {
            "start": "apply",
            "nodes": {
                "apply": {
                    "op": "工作区",
                    "action": "apply_search_replace",
                    "inputs": {"edits": "$ctx.edits"},
                    "atomic": True,
                    "edges": [{"condition": "edits_applied", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.apply.value", "edges": []},
            },
        }

        _, result = self.run_graph(
            graph,
            initial_data={"edits": [{"path": "demo.txt", "search": "alpha\n", "replace": "ALPHA\n"}]},
        )

        self.assertEqual(result.result["status"], "applied")
        self.assertEqual(source.read_bytes(), b"ALPHA\nbeta\n")

        source.write_bytes(b"alpha\r\nbeta\r\n")
        _, result = self.run_graph(
            graph,
            initial_data={"edits": [{"path": "demo.txt", "search": "alpha\n", "replace": "ALPHA\n"}]},
        )

        self.assertEqual(result.result["status"], "applied")
        self.assertEqual(source.read_bytes(), b"ALPHA\r\nbeta\r\n")

    def test_workspace_aider_partial_mode_keeps_success_and_returns_repair_feedback(self):
        source = self.root / "demo.txt"
        source.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        graph = {
            "start": "apply",
            "nodes": {
                "apply": {
                    "op": "工作区",
                    "action": "apply_search_replace",
                    "inputs": {"edits": "$ctx.edits"},
                    "atomic": False,
                    "edges": [{"condition": "edits_partial", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.apply.value", "edges": []},
            },
        }
        edits = [
            {"path": "demo.txt", "search": "alpha\n", "replace": "ALPHA\n"},
            {"path": "demo.txt", "search": "delta\n", "replace": "DELTA\n"},
        ]

        _, result = self.run_graph(graph, initial_data={"edits": edits})

        self.assertEqual(result.result["status"], "partial")
        self.assertEqual(source.read_text(encoding="utf-8"), "ALPHA\nbeta\ngamma\n")
        self.assertIn("failed to match", result.result["feedback"])
        self.assertIn("Do not resend", result.result["feedback"])

    def test_workspace_aider_atomic_mode_writes_nothing_when_one_edit_fails(self):
        source = self.root / "demo.txt"
        source.write_text("alpha\nbeta\n", encoding="utf-8")
        graph = {
            "start": "apply",
            "nodes": {
                "apply": {
                    "op": "工作区",
                    "action": "apply_search_replace",
                    "inputs": {"edits": "$ctx.edits"},
                    "atomic": True,
                    "edges": [{"condition": "edits_failed", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$node.apply.value", "edges": []},
            },
        }
        edits = [
            {"path": "demo.txt", "search": "alpha\n", "replace": "ALPHA\n"},
            {"path": "demo.txt", "search": "missing\n", "replace": "MISSING\n"},
        ]

        _, result = self.run_graph(graph, initial_data={"edits": edits})

        self.assertEqual(result.result["applied"], 0)
        self.assertEqual(source.read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_context_can_elide_old_observations_without_dropping_instance(self):
        messages = [
            {"role": "user", "message_type": "observation", "content": f"observation {index}\nline two"}
            for index in range(7)
        ]
        graph = {
            "start": "history",
            "nodes": {
                "history": {
                    "op": "上下文",
                    "action": "last_n_observations",
                    "source": "$ctx.messages",
                    "observation_last_n": 2,
                    "output_var": "processed",
                    "edges": [{"condition": "context_ready", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.processed", "edges": []},
            },
        }

        _, result = self.run_graph(graph, initial_data={"messages": messages})

        self.assertEqual(result.result[0]["content"], "observation 0\nline two")
        self.assertEqual(sum(bool(message.get("elided")) for message in result.result), 4)
        self.assertEqual(result.result[-2]["content"], "observation 5\nline two")
        self.assertEqual(result.result[-1]["content"], "observation 6\nline two")

    def test_end_session_tool_can_route_through_a_finalizer(self):
        class SubmittingAgent(FakeAgent):
            def execute_tool_call(self, _call):
                raise EndSession("implemented and verified")

        graph = {
            "start": "submit",
            "nodes": {
                "submit": {
                    "op": "工具",
                    "agent": "agent",
                    "inputs": {"tool_calls": "$ctx.calls"},
                    "end_session_to": "finalize",
                    "outputs": {"submission": "submission"},
                    "edges": [],
                },
                "finalize": {"op": "结束", "value": "$ctx.submission", "edges": []},
            },
        }
        calls = [{"id": "submit-1", "type": "function", "function": {"name": "submit_result", "arguments": "{}"}}]

        _, result = self.run_graph(graph, agents={"agent": SubmittingAgent()}, initial_data={"calls": calls})

        self.assertEqual(result.result, "implemented and verified")
        self.assertEqual(result.stats.tool_calls, 1)
        self.assertEqual(result.data["_trajectory"][0]["action"], "submit_result")

    def test_budget_limit_can_enter_a_safe_bounded_finalizer(self):
        events = []
        graph = {
            "start": "first",
            "max_steps": 1,
            "budget_exceeded_to": "capture_limit",
            "limit_finalizer_max_steps": 3,
            "nodes": {
                "first": {"op": "Agent", "agent": "agent", "edges": [{"condition": "has_text", "to": "second"}]},
                "second": {"op": "Agent", "agent": "agent", "edges": []},
                "capture_limit": {
                    "op": "数据",
                    "action": "set",
                    "key": "termination_reason",
                    "value": "$ctx._termination.message",
                    "edges": [{"condition": "default", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.termination_reason", "edges": []},
            },
        }

        _, result = self.run_graph(graph, events=events)

        self.assertIn("max model calls", result.result)
        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(result.data["_termination"]["node"], "second")
        self.assertEqual([payload["status"] for event, payload in events if event == "done"], ["budget_exceeded"])

    def test_budget_stops_additional_model_calls(self):
        graph = {
            "start": "first",
            "max_steps": 1,
            "nodes": {
                "first": {"op": "Agent", "agent": "agent", "edges": [{"condition": "has_text", "to": "second"}]},
                "second": {"op": "Agent", "agent": "agent", "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        with self.assertRaises(PipelineBudgetExceeded):
            PipelineRunner(harness).run()

    def test_provider_usage_and_cache_cost_are_recorded_and_budgeted(self):
        agent = FakeAgent()
        agent.llm.last_response_metadata = {
            "sequence": 1,
            "model": "served-model",
            "provider_request_ids": ["req-usage"],
            "attempts": 2,
            "retries": 1,
            "reconnects": 1,
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 7},
            },
        }
        graph = {
            "start": "think",
            "budget": {
                "max_tokens": 100,
                "prices": {
                    "input_per_million": 2,
                    "cached_input_per_million": 0.5,
                    "output_per_million": 4,
                },
            },
            "nodes": {
                "think": {"op": "Agent", "agent": "agent", "edges": [{"condition": "has_text", "to": "done"}]},
                "done": {"op": "结束", "inputs": {"value": "$last.text"}, "edges": []},
            },
        }

        _, result = self.run_graph(graph, agents={"agent": agent})

        self.assertEqual(result.stats.provider_requests, 1)
        self.assertEqual(result.stats.provider_retries, 2)
        self.assertEqual(result.stats.input_tokens_actual, 11)
        self.assertEqual(result.stats.cached_input_tokens_actual, 7)
        self.assertEqual(result.stats.output_tokens_actual, 3)
        self.assertEqual(result.stats.provider_request_ids, ["req-usage"])
        self.assertAlmostEqual(result.stats.cost_actual, (4 * 2 + 7 * 0.5 + 3 * 4) / 1_000_000)

        limited_graph = copy.deepcopy(graph)
        limited_graph["budget"]["max_tokens"] = 5
        limited_agent = FakeAgent()
        limited_agent.llm.last_response_metadata = copy.deepcopy(agent.llm.last_response_metadata)
        with self.assertRaisesRegex(PipelineBudgetExceeded, "provider-reported token budget"):
            self.run_graph(limited_graph, agents={"agent": limited_agent})

    def test_schema_reports_dangling_edges(self):
        errors = validate_pipeline({"start": "a", "nodes": {"a": {"op": "条件", "edges": [{"condition": "true", "to": "missing"}]}}})
        self.assertTrue(any("missing" in error for error in errors))

    def test_schema_reports_dangling_run_limit_finalizer(self):
        errors = validate_pipeline(
            {
                "start": "a",
                "budget_exceeded_to": "missing",
                "nodes": {"a": {"op": "输出", "edges": []}},
            }
        )
        self.assertIn("pipeline.budget_exceeded_to points to missing node: 'missing'", errors)

    def test_schema_reports_dangling_direct_node_route(self):
        errors = validate_pipeline(
            {
                "start": "a",
                "nodes": {"a": {"op": "工具", "end_session_to": "missing", "edges": []}},
            }
        )
        self.assertIn("node 'a'.end_session_to points to missing node 'missing'", errors)

        errors = validate_pipeline(
            {
                "start": "a",
                "nodes": {"a": {"op": "Agent", "auto_continue_to": "missing", "edges": []}},
            }
        )
        self.assertIn("node 'a'.auto_continue_to points to missing node 'missing'", errors)


if __name__ == "__main__":
    unittest.main()
