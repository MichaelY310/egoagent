from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_policy import context_blocks, conversation_turns
from harness import Session, get_current_harness
from pipeline_engine import PipelineError, PipelineRunner
from config import CONFIG


ROOT = Path(__file__).resolve().parents[1]


class FakeLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or ["{}"])
        self.calls = 0
        self.config = {"context_window": 128000}

    def chat(self, messages, **_kwargs):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return {"choices": [{"message": {"content": response}}]}


class FakeAgent:
    def __init__(self, replies=None, model_responses=None):
        self.name = "agent"
        self.workspace = None
        self.replies = list(replies or ["done"])
        self.calls = 0
        self.llm = FakeLLM(model_responses)

    def init_environment(self):
        return None

    def build_system_prompt(self, has_tools=True):
        return f"test identity; tools={has_tools}"

    def get_tools_desc(self):
        return []

    def step(self, messages, tools_desc=None, on_token=None):
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if on_token:
            on_token(text)
        harness = get_current_harness()
        message = {"role": "assistant", "name": self.name, "content": text}
        harness.session.record(message)
        harness.session.record_full(message.copy())
        return text, None


class FakeHarness:
    def __init__(self, root: Path, graph: dict, agent: FakeAgent | None = None):
        self.dir = root
        self.workspace = root
        self.config = {"name": "component_test", "pipeline": graph}
        self.name = "component_test"
        self.agents = {"agent": agent or FakeAgent()}
        self.prompts = {}
        self.session = Session(workspace=root, save_dir=None)
        self.parent = None
        self.children = []
        self.slots = {"agent": {}}
        self.return_mode = "last"
        self._non_interactive = True

    def set_agents(self, agents):
        self.agents = agents


class DagComponentTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_graph(self, graph, *, messages=None, agent=None, initial_data=None, events=None):
        harness = FakeHarness(self.root, graph, agent)
        if messages:
            harness.session.messages = copy.deepcopy(messages)
            harness.session.full_messages = copy.deepcopy(messages)
        result = PipelineRunner(
            harness,
            initial_data=initial_data,
            get_input=lambda: None,
            is_running=lambda: True,
            on_output=lambda event, payload: events.append((event, payload)) if events is not None else None,
        ).run()
        return harness, result

    def test_conversation_snapshot_is_a_read_only_model_input_port(self):
        messages = []
        for index in range(4):
            messages.extend([
                {"role": "user", "content": (f"request {index} " * 180)},
                {"role": "assistant", "content": (f"answer {index} " * 180)},
            ])
        graph = {
            "start": "snapshot",
            "nodes": {
                "snapshot": {
                    "op": "上下文", "action": "snapshot", "review_interval": 2,
                    "protect_recent_turns": 1, "context_limit_tokens": 64,
                    "output_var": "snapshot", "edges": [{"condition": "conversation_ready", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.snapshot", "edges": []},
            },
        }
        harness, result = self.run_graph(graph, messages=messages)

        self.assertEqual(result.stats.model_calls, 0)
        self.assertEqual(harness.session.messages, messages)
        self.assertTrue(result.result["review_triggered"])
        self.assertTrue(result.result["pressure"]["triggered"])
        self.assertEqual(len(result.result["review_batch"]), 2)
        self.assertIsInstance(json.loads(result.result["model_payload"]), dict)

    def test_conversation_output_applies_model_plan_but_preserves_full_audit(self):
        messages = [
            {"role": "user", "content": "unrelated weather chat"},
            {"role": "assistant", "content": "sunny"},
            {"role": "user", "content": "keep project requirement: port 7319"},
            {"role": "assistant", "content": "working on port 7319"},
        ]
        old_turn = conversation_turns(messages)[0]
        plan = {"decisions": [{"turn_id": old_turn.id, "action": "elide", "reason": "unrelated"}]}
        graph = {
            "start": "apply",
            "nodes": {
                "apply": {
                    "op": "上下文", "action": "apply", "apply_mode": "turn_plan",
                    "protect_recent_turns": 1, "inputs": {"plan": "$ctx.plan"},
                    "output_var": "context_result", "edges": [{"condition": "conversation_applied", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.context_result.stats", "edges": []},
            },
        }
        harness, result = self.run_graph(graph, messages=messages, initial_data={"plan": plan})

        self.assertNotIn("weather", json.dumps(harness.session.messages))
        self.assertIn("weather", json.dumps(harness.session.full_messages))
        self.assertGreater(result.result["saved_tokens_estimated"], 0)
        self.assertEqual(harness.session.state["context_governance"]["last_mode"], "turn_plan")

    def test_declared_subdag_contract_shares_conversation_and_maps_outputs(self):
        messages = []
        for index in range(4):
            messages.extend([
                {"role": "user", "content": f"old topic {index}"},
                {"role": "assistant", "content": f"old answer {index}"},
            ])
        turn_id = conversation_turns(messages)[0].id
        model_plan = json.dumps({
            "decisions": [{"turn_id": turn_id, "action": "elide", "reason": "test obsolete turn"}],
        })
        agent = FakeAgent(model_responses=[model_plan])
        graph = {
            "start": "component",
            "budget": {"max_model_calls": 3},
            "nodes": {
                "component": {
                    "op": "子流程", "harness": "component_context_curator", "share_session": True,
                    "agent_map": {"curator": "agent"},
                    "component_inputs": {"review_interval": 2, "protect_recent_turns": 1, "max_tool_chars": 0},
                    "component_outputs": {"applied": "parent.applied", "stats": "parent.stats"},
                    "result_mode": "data", "edges": [{"condition": "component_done", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.parent", "edges": []},
            },
        }
        harness, result = self.run_graph(graph, messages=messages, agent=agent)

        self.assertTrue(result.result["applied"])
        self.assertGreater(result.result["stats"]["saved_tokens_estimated"], 0)
        self.assertNotIn("old topic 0", json.dumps(harness.session.messages))
        self.assertIn("old topic 0", json.dumps(harness.session.full_messages))
        self.assertEqual(agent.llm.calls, 1)

    def test_no_implicit_context_model_call_without_declared_policy(self):
        history = [
            {"role": "user", "content": "large requirement " * 800},
            {"role": "assistant", "content": "large analysis " * 800},
        ]
        agent = FakeAgent(replies=["final"])
        events = []
        graph = {
            "start": "agent",
            "nodes": {
                "agent": {"op": "Agent", "agent": "agent", "inputs": {"messages": "$ctx.history"}, "edges": [{"condition": "has_text", "to": "done"}]},
                "done": {"op": "结束", "value": "$last.text", "edges": []},
            },
        }
        _harness, result = self.run_graph(graph, agent=agent, initial_data={"history": history}, events=events)

        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(agent.llm.calls, 0)
        self.assertNotIn("context_pressure", [name for name, _payload in events])

    def test_component_parse_failure_keeps_context_and_does_not_mark_reviewed(self):
        messages = []
        for index in range(4):
            messages.extend([
                {"role": "user", "content": f"requirement {index}"},
                {"role": "assistant", "content": f"answer {index}"},
            ])
        agent = FakeAgent(model_responses=["not valid json"])
        graph = {
            "start": "component",
            "budget": {"max_model_calls": 2},
            "nodes": {
                "component": {
                    "op": "子流程", "harness": "component_context_curator", "share_session": True,
                    "agent_map": {"curator": "agent"},
                    "component_inputs": {"review_interval": 2, "protect_recent_turns": 1, "max_tool_chars": 0},
                    "component_outputs": {"applied": "parent.applied"},
                    "result_mode": "data", "edges": [{"condition": "component_done", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.parent", "edges": []},
            },
        }
        harness, result = self.run_graph(graph, messages=messages, agent=agent)

        self.assertFalse(result.result["applied"])
        self.assertEqual(harness.session.messages, messages)
        self.assertEqual(harness.session.full_messages, messages)
        self.assertNotIn("context_governance", harness.session.state)

    def test_agent_designer_component_exposes_spec_before_any_mutation(self):
        spec = {
            "name": "paper_scout", "description": "Find local evidence", "role": "paper scout",
            "traits": ["careful"], "skills": ["read", "search"], "knowledge_topics": ["papers"],
            "system_prompt": "Prefer local evidence and cite exact paths.", "acceptance_test": "cite one local paper",
        }
        agent = FakeAgent(model_responses=[json.dumps(spec)])
        graph = {
            "start": "component",
            "budget": {"max_model_calls": 2},
            "nodes": {
                "component": {
                    "op": "子流程", "harness": "component_agent_designer", "share_session": False,
                    "agent_map": {"architect": "agent"},
                    "component_inputs": {"request": "Create a local paper scout", "require_approval": True},
                    "component_outputs": {"spec": "designed.spec", "completed": "designed.completed"},
                    "result_mode": "data", "edges": [{"condition": "component_done", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.designed", "edges": []},
            },
        }
        _harness, result = self.run_graph(graph, agent=agent)

        self.assertEqual(result.result["spec"]["name"], "paper_scout")
        self.assertFalse(result.result["completed"])
        self.assertEqual(agent.llm.calls, 1)

    def test_subdag_output_schema_is_enforced_before_parent_mapping(self):
        repository = self.root / "harnesses"
        child_dir = repository / "typed_child"
        child_dir.mkdir(parents=True)
        child_config = {
            "name": "typed_child", "description": "typed output", "slots": {}, "prompts": {}, "return_mode": "last",
            "component": {
                "inputs": {},
                "outputs": {"score": {"path": "score", "schema": {"type": "string"}}},
            },
            "pipeline": {
                "start": "set", "max_steps": 4, "workspace_preview": False,
                "nodes": {
                    "set": {"op": "数据", "action": "set", "key": "score", "value": 7, "edges": [{"condition": "default", "to": "done"}]},
                    "done": {"op": "结束", "value": "$ctx.score", "edges": []},
                },
            },
        }
        (child_dir / "config.json").write_text(json.dumps(child_config), encoding="utf-8")
        graph = {
            "start": "child",
            "nodes": {
                "child": {"op": "子流程", "harness": "typed_child", "component_outputs": {"score": "parent.score"}, "edges": []},
            },
        }
        with patch.dict(CONFIG, {"harness_template_repository": str(repository)}):
            with self.assertRaisesRegex(PipelineError, "SubDAG output 'score' is invalid"):
                self.run_graph(graph)


if __name__ == "__main__":
    unittest.main()
