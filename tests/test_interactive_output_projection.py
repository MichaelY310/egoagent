from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from harness_editor import server as server_module


class InteractiveOutputProjectionTests(unittest.TestCase):
    def setUp(self):
        self.handle = server_module.interactive_runs.create(
            Path(__file__).resolve().parents[1],
        )

    def tearDown(self):
        self.handle.state["running"] = False
        server_module.interactive_runs.remove(self.handle.run_id)

    def emit(self, event: str, data: dict) -> None:
        with server_module.interactive_runs.bind(self.handle), patch.object(server_module, "notify_clients"):
            server_module.notify_output(event, data)

    def test_two_model_turns_from_same_agent_remain_two_outputs(self):
        first = "你好！有什么可以帮你的吗？"
        second = "你好！我还在。"

        self.emit("token", {"agent": "agent", "text": first})
        self.emit("model_response", {"agent": "agent", "text": first, "tool_calls": []})
        self.emit("input_required", {"node_id": "input"})
        self.emit("token", {"agent": "agent", "text": second})
        self.emit("model_response", {"agent": "agent", "text": second, "tool_calls": []})

        self.assertEqual([item["text"] for item in self.handle.outputs], [first, second])
        self.assertTrue(all(item["sealed"] for item in self.handle.outputs))

    def test_non_streaming_model_response_still_creates_visible_output(self):
        self.emit("model_response", {"agent": "agent", "text": "直接回答", "tool_calls": []})
        self.assertEqual(self.handle.outputs[0]["text"], "直接回答")
        self.assertTrue(self.handle.outputs[0]["sealed"])

    def test_pipeline_run_identity_is_exposed_for_change_review(self):
        self.emit("run_started", {
            "run_id": "pipeline-123",
            "change_transaction_id": "run-pipeline-123",
        })

        self.assertEqual(self.handle.state["pipeline_run_id"], "pipeline-123")
        self.assertEqual(self.handle.state["change_transaction_id"], "run-pipeline-123")


if __name__ == "__main__":
    unittest.main()
