import json
import tempfile
import unittest
from pathlib import Path

from interactive_execution_service import InteractiveExecutionError, InteractiveExecutionService
from interactive_runs import InteractiveRunManager


class InteractiveExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.notifications = []
        self.manager = InteractiveRunManager()
        self.service = InteractiveExecutionService(
            self.manager,
            notify=lambda state: self.notifications.append(dict(state)),
        )

    def tearDown(self):
        self.temp.cleanup()

    def _running(self):
        handle = self.manager.create(self.root)
        handle.state.update({"running": True, "status": "running"})
        return handle

    def test_debug_directive_is_scoped_to_the_addressed_run(self):
        first = self._running()
        second = self._running()
        first.state.update({"paused": True, "pending_node": "model", "pause_reason": "before"})

        result = self.service.control({
            "run_id": first.run_id,
            "action": "override_inputs",
            "node_id": "model",
            "inputs": {"query": "new"},
        })

        self.assertTrue(result["ok"])
        self.assertEqual(first.node_directive["inputs"], {"query": "new"})
        self.assertIsNone(second.node_directive)

    def test_approval_nonce_is_consumed_exactly_once(self):
        handle = self._running()
        handle.state["pending_approval"] = {"approval_id": "approve-1"}
        result = self.service.approval({
            "run_id": handle.run_id,
            "approval_id": "approve-1",
            "decision": "approved",
        })
        self.assertEqual(result["decision"], "approved")
        self.assertEqual(json.loads(handle.input_queue.get_nowait())["decision"], "approved")
        with self.assertRaises(InteractiveExecutionError) as raised:
            self.service.approval({
                "run_id": handle.run_id,
                "approval_id": "approve-1",
                "decision": "approved",
            })
        self.assertEqual(raised.exception.status, 409)

    def test_input_cannot_bypass_pending_approval_and_stop_unblocks_worker(self):
        handle = self._running()
        handle.state["pending_approval"] = {"approval_id": "danger"}
        with self.assertRaises(InteractiveExecutionError) as raised:
            self.service.input({"run_id": handle.run_id, "text": "yes"})
        self.assertEqual(raised.exception.status, 409)

        result = self.service.stop({"run_id": handle.run_id})
        self.assertTrue(result["ok"])
        self.assertFalse(handle.state["running"])
        self.assertIsNone(handle.input_queue.get_nowait())


if __name__ == "__main__":
    unittest.main()
