import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from heart_flow.service import FlowRelayService, enabled


class HeartFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = self.root / "sessions" / "demo"
        self.session.mkdir(parents=True)
        (self.session / "full_messages.json").write_text(json.dumps([
            {"role": "user", "content": "[代码附件: src/garden.py:1-4] 修复 src/garden.py 并运行 pytest。[EgoAgent planned context] <context>large payload</context>"},
            {"role": "user", "content": "<tool_response>{\"content\":\"not the user goal\"}</tool_response>"},
            {"role": "assistant", "content": "已修复阈值判断。\npytest tests/test_garden.py: 4 passed\n下一步：检查 src/controller.py 的边界情况。\n当前阻塞：需要用户允许运行集成测试。"},
        ], ensure_ascii=False), encoding="utf-8")
        self.service = FlowRelayService(self.root / "heart_flow.json")
        self.project = {"id": "p1", "title": "Garden", "workspace": str(self.root)}
        self.session_info = {"name": "demo", "path": str(self.session), "message_count": 2}

    def tearDown(self):
        self.temp.cleanup()

    def test_capsule_is_grounded_and_editable(self):
        capsule = self.service.park(project=self.project, session=self.session_info)
        self.assertIn("garden.py", " ".join(capsule["files"]))
        self.assertIn("controller.py", " ".join(capsule["files"]))
        self.assertNotIn("tool_response", capsule["goal"])
        self.assertNotIn("planned context", capsule["goal"])
        self.assertIn("检查", capsule["next_action"])
        self.assertTrue(capsule["tests"])
        self.assertTrue(capsule["blockers"])
        edited = self.service.park(
            project=self.project,
            session=self.session_info,
            overrides={"next_action": "先写一个边界测试"},
        )
        self.assertEqual(edited["next_action"], "先写一个边界测试")

    def test_focus_and_attention_router_batch_background_events(self):
        self.service.focus("p1", minutes=25)
        runs = [
            {"run_id": "r1", "project_id": "p1", "running": True},
            {"run_id": "r2", "project_id": "p2", "running": True},
        ]
        self.service.observe_runs(runs)
        self.assertEqual(self.service.snapshot(projects=[self.project], runs=runs)["inbox"], [])

        runs[0].update({"running": False, "waiting_for_input": True, "session_name": "s1"})
        runs[1].update({"running": False, "waiting_for_input": True, "session_name": "s2"})
        snapshot = self.service.snapshot(
            projects=[self.project, {"id": "p2", "title": "Other", "workspace": str(self.root)}],
            runs=runs,
        )
        delivery = {event["run_id"]: event["delivery"] for event in snapshot["inbox"]}
        self.assertEqual(delivery, {"r1": "now", "r2": "batched"})

        # Re-reading the same run state must not create duplicate notifications.
        again = self.service.snapshot(projects=[self.project], runs=runs)
        self.assertEqual(len(again["inbox"]), 2)

    def test_approval_is_urgent_even_for_background_project(self):
        self.service.focus("p1")
        snapshot = self.service.snapshot(projects=[self.project], runs=[{
            "run_id": "approval-run",
            "project_id": "p2",
            "running": True,
            "pending_approval": {"id": "a1"},
        }])
        self.assertEqual(snapshot["inbox"][0]["phase"], "approval")
        self.assertEqual(snapshot["inbox"][0]["delivery"], "now")

    def test_feature_flag(self):
        with patch.dict(os.environ, {"EGOAGENT_HEART_FLOW_ENABLED": "0"}):
            self.assertFalse(enabled())
        with patch.dict(os.environ, {"EGOAGENT_HEART_FLOW_ENABLED": "1"}):
            self.assertTrue(enabled())


if __name__ == "__main__":
    unittest.main()
