import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness import Session, runtime_scope
from agent_factory import AgentFactory
from subagent_lifecycle import finish_subagent, link_subagent


class SubagentLifecycleTests(unittest.TestCase):
    def test_product_adaptive_identity_combines_execution_and_evolution_tools(self):
        project_root = Path(__file__).resolve().parent.parent
        agent = AgentFactory(identity_roots=(project_root / "identity",)).create(
            "adaptive_deepseek_coder", workspace=project_root
        )
        tools = {agent._short_name(name) for name in agent.tools}
        required = {
            "read_file", "patch_file", "run_command", "search_capabilities",
            "activate_capability", "create_harness", "create_skill", "create_knowledge",
        }
        self.assertFalse(required - tools)
        self.assertFalse(agent.llm.enable_thinking)

    def test_coder_exposes_the_complete_isolated_subagent_contract(self):
        project_root = Path(__file__).resolve().parent.parent
        skill_root = project_root / "identity" / "coder" / "ego" / "skills" / "create_harness"
        metadata = json.loads((skill_root / "meta.json").read_text(encoding="utf-8"))
        properties = metadata["parameters"]["properties"]
        for name in ("initial_message", "max_result_chars", "include_metadata"):
            self.assertIn(name, properties)

        namespace = {}
        exec((skill_root / "scripts" / "create_harness.py").read_text(encoding="utf-8"), namespace)
        parameters = inspect.signature(namespace["create_harness"]).parameters
        for name in ("initial_message", "max_result_chars", "include_metadata", "_context"):
            self.assertIn(name, parameters)

    def test_lifecycle_is_both_durable_and_projected_to_the_live_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            parent = SimpleNamespace(
                name="parent_flow",
                workspace=workspace,
                session=Session(workspace=workspace, save_dir=workspace / "parent-session"),
                agents={},
                children=[],
            )
            child = SimpleNamespace(
                name="result_only_search",
                workspace=workspace,
                session=Session(workspace=workspace),
                agents={},
                children=[],
                parent=None,
            )
            live_events = []
            run_context = SimpleNamespace(
                harness=parent,
                current_node="delegate",
                graph={"nodes": {"delegate": {"op": "子流程"}}},
                emit=lambda event, data: live_events.append((event, data)),
                secret_view=None,
                run_id="run_parent",
                parent_run_id=None,
            )

            with runtime_scope(run_context=run_context):
                invocation = link_subagent(parent, child, share_session=False, purpose="capability discovery")
                result = finish_subagent(child, status="completed", result={"matches": ["tool-a"]})

            self.assertIn(child, parent.children)
            self.assertEqual(result.invocation_id, invocation.invocation_id)
            self.assertEqual([event for event, _ in live_events], ["subagent_spawned", "subagent_completed"])
            self.assertEqual(live_events[0][1]["child_harness"], "result_only_search")
            self.assertEqual(live_events[1][1]["status"], "completed")
            from trajectory import TrajectoryReader
            durable = TrajectoryReader(parent.session.trajectory.native_path).read_all()
            self.assertEqual([event["type"] for event in durable], ["subagent.spawned", "subagent.completed"])


if __name__ == "__main__":
    unittest.main()
