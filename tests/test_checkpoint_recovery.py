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

from harness import Session, get_current_harness
from pipeline_engine import (
    PipelineInDoubt,
    PipelineRevisionConflict,
    PipelineRunner,
)


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, **_kwargs):
        self.calls += 1
        self.last_messages = messages
        return {"choices": [{"message": {"content": "model-result"}}]}


class FakeAgent:
    def __init__(self):
        self.name = "agent"
        self.llm = FakeLLM()
        self.tool_calls = 0
        self.workspace = None

    def init_environment(self):
        return None

    def build_system_prompt(self, has_tools=True):
        return f"test-agent tools={has_tools}"

    def get_tools_desc(self):
        return []

    def execute_tool_call(self, call, **_kwargs):
        self.tool_calls += 1
        return f"tool:{call['function']['name']}"


class FakeHarness:
    def __init__(self, root: Path, graph: dict, agent: FakeAgent):
        self.dir = root
        self.workspace = root
        self.name = "checkpoint-recovery"
        self.config = {"name": self.name, "pipeline": copy.deepcopy(graph)}
        self.agents = {"agent": agent}
        self.prompts = {"test": "{value}"}
        self.session = Session(workspace=root, save_dir=None)
        self.parent = None
        self.children = []
        self.slots = {"agent": {}}
        self.return_mode = "last"
        self._non_interactive = True

    def set_agents(self, agents):
        self.agents = agents
        self.slots = {name: {} for name in agents}


class SimulatedCrash(RuntimeError):
    pass


def recovery_graph() -> dict:
    inline = {
        "start": "copy",
        "nodes": {
            "copy": {
                "op": "数据", "action": "set", "key": "answer", "value": "$ctx.number",
                "edges": [{"condition": "default", "to": "done"}],
            },
            "done": {"op": "结束", "value": {"answer": "$ctx.answer"}, "edges": []},
        },
    }
    return {
        "start": "model",
        "context": {
            "calls": [{
                "id": "once-tool",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }],
            "map_items": ["alpha", "beta"],
            "loop_items": [1, 2],
        },
        "max_steps": 100,
        "nodes": {
            "model": {
                "op": "模型", "agent": "agent", "prompt": "test",
                "edges": [{"condition": "has_text", "to": "tool"}],
            },
            "tool": {
                "op": "工具", "agent": "agent", "inputs": {"tool_calls": "$ctx.calls"},
                "edges": [{"condition": "tools_executed", "to": "process"}],
            },
            "process": {
                "op": "进程", "command": sys.executable,
                "args": [
                    "-c",
                    "from pathlib import Path; p=Path('marker.txt'); "
                    "p.write_text((p.read_text(encoding='utf-8') if p.exists() else '')+'x', encoding='utf-8')",
                ],
                "edges": [{"condition": "process_succeeded", "to": "map"}],
            },
            "map": {
                "op": "映射", "source": "$ctx.map_items", "item_var": "map_item",
                "body_start": "map_read", "join": "map_join", "output_var": "mapped",
                "edges": [],
            },
            "map_read": {
                "op": "数据", "action": "get", "key": "map_item",
                "edges": [{"condition": "default", "to": "map_join"}],
            },
            "map_join": {
                "op": "合并", "source": "$ctx.mapped", "strategy": "list",
                "edges": [{"condition": "default", "to": "loop"}],
            },
            "loop": {
                "op": "循环", "list_var": "loop_items", "item_var": "loop_item",
                "body_start": "loop_record", "result_var": "loop_results",
                "edges": [{"condition": "loop_done", "to": "child"}],
            },
            "loop_record": {
                "op": "数据", "action": "set", "key": "_loop_result", "value": "$ctx.loop_item",
                "edges": [{"condition": "default", "to": "loop"}],
            },
            "child": {
                "op": "子流程", "inline_pipeline": inline, "result_mode": "result",
                "inputs": {"data": {"number": 7}}, "output_var": "child_result",
                "edges": [{"condition": "subflow_done", "to": "done"}],
            },
            "done": {
                "op": "结束",
                "value": {
                    "model": "$node.model.text",
                    "mapped": "$ctx.mapped",
                    "loop": "$ctx.loop_results",
                    "child": "$ctx.child_result",
                },
                "edges": [],
            },
        },
    }


class CheckpointRecoveryTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _crash_after(self, target: str):
        graph = recovery_graph()
        agent = FakeAgent()
        events = []

        def after_node(_context, node_id, _node):
            if node_id == target:
                raise SimulatedCrash(f"crash after {target}")

        with self.assertRaises(SimulatedCrash):
            PipelineRunner(
                FakeHarness(self.root, graph, agent),
                auto_checkpoint=True,
                after_node=after_node,
                on_output=lambda event, payload: events.append((event, payload)),
            ).run()
        completed = [
            payload for event, payload in events
            if event == "checkpoint" and payload.get("phase") == "completed"
        ]
        self.assertTrue(completed)
        checkpoint = completed[-1]["path"]
        resumed = PipelineRunner(
            FakeHarness(self.root, graph, agent),
            auto_checkpoint=True,
            resume_from=checkpoint,
        ).run()
        return agent, resumed, Path(checkpoint)

    def test_model_tool_process_map_loop_and_child_resume_without_replay(self):
        for target in ("model", "tool", "process", "map", "loop", "child"):
            with self.subTest(target=target):
                case_root = self.root / target
                case_root.mkdir()
                original_root = self.root
                self.root = case_root
                try:
                    agent, resumed, checkpoint = self._crash_after(target)
                    self.assertEqual(agent.llm.calls, 1)
                    self.assertEqual(agent.tool_calls, 1)
                    self.assertEqual((case_root / "marker.txt").read_text(encoding="utf-8"), "x")
                    self.assertEqual(resumed.result["child"], {"answer": 7})
                    self.assertEqual(resumed.result["loop"], [1, 2])
                    self.assertEqual(len([step for step in resumed.completed_steps if step["node"] == "loop"]), 3)
                    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                    self.assertEqual(payload["version"], 3)
                    for field in (
                        "revisions", "pending_approvals", "artifacts", "change_transaction",
                        "child_run_tree", "completed_steps", "permission_policy", "stats",
                    ):
                        self.assertIn(field, payload)
                finally:
                    self.root = original_root

    def test_manual_edit_causes_revision_conflict_and_is_never_overwritten(self):
        _agent, _resumed, checkpoint = self._crash_after("process")
        marker = self.root / "marker.txt"
        marker.write_text("manual-newer-edit", encoding="utf-8")

        with self.assertRaises(PipelineRevisionConflict) as raised:
            PipelineRunner(
                FakeHarness(self.root, recovery_graph(), FakeAgent()),
                auto_checkpoint=True,
                resume_from=str(checkpoint),
            )

        self.assertEqual(marker.read_text(encoding="utf-8"), "manual-newer-edit")
        self.assertTrue(any(item["resource"] == "workspace" for item in raised.exception.conflicts))

    def test_inflight_side_effect_requires_explicit_inspection_confirmation(self):
        graph = recovery_graph()
        events = []

        class CrashBeforeProcessRunner(PipelineRunner):
            def _execute_with_policy(self, node_id, node, op):
                if node_id == "process":
                    raise SimulatedCrash("worker vanished")
                return super()._execute_with_policy(node_id, node, op)

        with self.assertRaises(SimulatedCrash):
            CrashBeforeProcessRunner(
                FakeHarness(self.root, graph, FakeAgent()),
                start="process",
                auto_checkpoint=True,
                on_output=lambda event, payload: events.append((event, payload)),
            ).run()
        checkpoint = [
            payload["path"] for event, payload in events
            if event == "checkpoint" and payload.get("phase") == "in_flight"
        ][-1]

        with self.assertRaises(PipelineInDoubt):
            PipelineRunner(FakeHarness(self.root, graph, FakeAgent()), resume_from=checkpoint)

        resumed = PipelineRunner(
            FakeHarness(self.root, graph, FakeAgent()),
            resume_from=checkpoint,
            auto_checkpoint=True,
            allow_inflight_resume=True,
        ).run()
        self.assertEqual((self.root / "marker.txt").read_text(encoding="utf-8"), "x")
        self.assertEqual(resumed.result["child"], {"answer": 7})


if __name__ == "__main__":
    unittest.main()
