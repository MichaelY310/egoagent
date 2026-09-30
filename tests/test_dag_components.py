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
        self.activated_capabilities = []

    def init_environment(self):
        return None

    def build_system_prompt(self, has_tools=True):
        return f"test identity; tools={has_tools}"

    def get_tools_desc(self):
        return []

    def activate_capability(self, capability_id, registry=None):
        self.activated_capabilities.append(capability_id)
        return {"ok": True, "id": capability_id, "kind": "skill", "name": "fixture_skill"}

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

    def test_conversation_snapshot_can_include_durable_usage_without_payloads(self):
        graph = {
            "start": "snapshot",
            "nodes": {
                "snapshot": {
                    "op": "上下文", "action": "snapshot", "include_usage": True,
                    "output_var": "snapshot", "edges": [{"condition": "conversation_ready", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.snapshot", "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        harness.session.set_save_dir(self.root / "usage-session")
        harness.session.trace(
            "model.response",
            {
                "content": "secret response must not enter usage summary",
                "reasoning": "hidden reasoning",
                "tool_calls": [],
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
                "provider_metadata": {},
            },
            agent="agent",
            model_call_id="call_fixture",
        )
        harness.session.trace(
            "tool.result",
            {"name": "read_file", "status": "completed", "result": "large private output"},
            agent="agent",
            tool_call_id="tool_fixture",
        )
        result = PipelineRunner(harness, get_input=lambda: None, is_running=lambda: True).run()

        usage = result.result["usage"]
        self.assertEqual(usage["source"], "session_trajectory")
        self.assertEqual(usage["model_calls"], 1)
        self.assertEqual(usage["tool_calls"], 1)
        self.assertEqual(usage["tokens_actual"], 150)
        self.assertEqual(usage["cached_input_tokens_actual"], 80)
        self.assertNotIn("secret response", json.dumps(usage))
        self.assertEqual(json.loads(result.result["model_payload"])["usage"]["tokens_actual"], 150)

    def test_failed_authored_identity_capability_can_be_quarantined_from_evidence(self):
        identity_root = self.root / "identity"
        capability = identity_root / "fixture" / "ego" / "skills" / "bad_skill"
        capability.mkdir(parents=True)
        (capability / "meta.json").write_text('{"type":"tool","name":"bad_skill"}', encoding="utf-8")
        evidence = [{
            "name": "create_skill",
            "result": {"ok": True, "path": str(capability)},
        }]
        graph = {
            "start": "quarantine",
            "nodes": {
                "quarantine": {
                    "op": "能力", "action": "quarantine_from_evidence",
                    "inputs": {"source": "$ctx.evidence", "reason": "verification failed"},
                    "output_var": "quarantine_result",
                    "edges": [{"condition": "quarantined", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.quarantine_result", "edges": []},
            },
        }
        with patch.dict(CONFIG, {"identity_repository": identity_root}):
            _, result = self.run_graph(graph, initial_data={"evidence": evidence})

        self.assertTrue(result.result["ok"])
        self.assertFalse(capability.exists())
        quarantined = Path(result.result["quarantine_path"])
        self.assertTrue(quarantined.is_dir())
        self.assertTrue((quarantined / "meta.json").is_file())

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

    def test_capability_activation_evidence_parser_rejects_prose_and_extracts_tool_result(self):
        evidence = [{
            "name": "activate_capability",
            "result": json.dumps({"ok": True, "id": "skill:identity/demo/tool", "kind": "skill"}),
        }]

        self.assertEqual(
            PipelineRunner._capability_id_from_evidence(evidence),
            "skill:identity/demo/tool",
        )
        self.assertIsNone(PipelineRunner._capability_id_from_evidence(
            "Activated skill:identity/demo/untrusted in prose"
        ))

    @patch("capability_registry.CapabilityRegistry")
    def test_capability_node_deterministically_activates_only_unambiguous_match(self, registry_type):
        registry = registry_type.return_value
        registry.search.return_value = {
            "results": [
                {"id": "skill:exact", "score": 4.2, "lexical_score": 10.0, "semantic_score": 0.72, "query_coverage": 0.2},
                {"id": "skill:adjacent", "score": 1.9, "lexical_score": 2.0, "semantic_score": 0.2, "query_coverage": 0.2},
            ]
        }
        agent = FakeAgent()
        graph = {
            "start": "capability",
            "nodes": {
                "capability": {
                    "op": "能力", "action": "search_and_activate", "agent": "agent",
                    "query": "exact fixture transformation",
                    "edges": [{"condition": "activated", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$last.activation", "edges": []},
            },
        }

        _harness, result = self.run_graph(graph, agent=agent)

        self.assertEqual(agent.activated_capabilities, ["skill:exact"])
        self.assertTrue(result.result["ok"])
        self.assertEqual(result.result["selection"]["method"], "deterministic_high_confidence")
        registry.record_event.assert_called_once_with("skill:exact", "activate")

    @patch("capability_registry.CapabilityRegistry")
    def test_capability_node_does_not_auto_activate_lexical_but_semantically_adjacent_skill(self, registry_type):
        registry = registry_type.return_value
        registry.search.return_value = {
            "results": [
                {"id": "skill:wrong-contract", "score": 8.0, "lexical_score": 12.0, "semantic_score": 0.53, "query_coverage": 0.95},
                {"id": "skill:other", "score": 1.0, "lexical_score": 1.0, "semantic_score": 0.1, "query_coverage": 0.1},
            ]
        }
        agent = FakeAgent()
        graph = {
            "start": "capability",
            "nodes": {
                "capability": {
                    "op": "能力", "action": "search_and_activate", "agent": "agent",
                    "query": "normalize a different release contract",
                    "edges": [{"condition": "not_found", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$last.activation", "edges": []},
            },
        }

        _harness, result = self.run_graph(graph, agent=agent)

        self.assertEqual(agent.activated_capabilities, [])
        self.assertFalse(result.result["ok"])
        self.assertEqual(result.result["status"], "not_found")
        registry.record_event.assert_not_called()

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

    def test_successful_mutation_evidence_exposes_only_its_persisted_path(self):
        evidence = [{
            "name": "create_skill",
            "result": json.dumps({
                "ok": True,
                "kind": "skill",
                "name": "normalize_bundle_json",
                "path": str(self.root / "identity" / "skills" / "normalize_bundle_json"),
            }),
        }]

        self.assertEqual(
            PipelineRunner._capability_path_from_mutation_evidence(evidence),
            str(self.root / "identity" / "skills" / "normalize_bundle_json"),
        )
        self.assertIsNone(PipelineRunner._capability_path_from_mutation_evidence({
            "name": "create_skill",
            "result": {"ok": False, "path": "must-not-load"},
        }))

    def test_capability_node_hot_loads_a_persisted_mutation_on_parent_agent(self):
        capability_path = ROOT / "identity" / "coder" / "ego" / "skills" / "create_skill"
        evidence = [{
            "name": "create_skill",
            "result": json.dumps({"ok": True, "kind": "skill", "path": str(capability_path)}),
        }]
        agent = FakeAgent()
        graph = {
            "start": "activate",
            "nodes": {
                "activate": {
                    "op": "能力",
                    "action": "activate_from_evidence",
                    "agent": "agent",
                    "inputs": {"source": evidence},
                    "edges": [{"condition": "activated", "to": "done"}],
                },
                "done": {"op": "结束", "value": "ok", "edges": []},
            },
        }

        _harness, result = self.run_graph(graph, agent=agent)

        self.assertEqual(result.result, "ok")
        self.assertEqual(len(agent.activated_capabilities), 1)

    def test_structured_capability_search_evidence_can_be_ranked_without_model_prose(self):
        search = {
            "query": "bundle normalization",
            "results": [{"id": "skill:bundle", "kind": "skill", "score": 4.0}],
        }
        envelope = [{"name": "search_capabilities", "result": search}]

        self.assertEqual(PipelineRunner._capability_search_from_evidence(envelope), search)
        self.assertIsNone(PipelineRunner._capability_search_from_evidence("the model says it found a skill"))


if __name__ == "__main__":
    unittest.main()
