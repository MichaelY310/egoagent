import json
import tempfile
import threading
import time
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

    def test_start_records_the_control_surface(self):
        def worker():
            return None

        handle = self.service.start(
            workspace=self.root,
            harness="demo",
            agents={"agent": "identity/coder"},
            debug_mode="auto",
            mode="agent",
            surface="builder",
            mutation_targets=[],
            security={},
            sandbox={},
            worker_target=worker,
            worker_args=(),
        )
        if handle.thread:
            handle.thread.join(timeout=1)
        self.assertEqual(handle.state["surface"], "builder")

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
        self.assertEqual(handle.wait_for_approval("approve-1", lambda: False)["decision"], "approved")
        self.assertTrue(handle.input_queue.empty())
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

    def test_stop_can_wait_for_a_reconfigured_worker_to_finalize(self):
        released = threading.Event()

        def worker(handle):
            while handle.state.get("running"):
                time.sleep(0.005)
            released.set()

        handle = self.service.start(
            workspace=self.root,
            harness="demo",
            agents={"agent": "identity/coder"},
            debug_mode="auto",
            mode="agent",
            surface="chat",
            mutation_targets=[],
            security={},
            sandbox={},
            worker_target=worker,
            worker_args=lambda created: (created,),
            session_name="logical_session",
        )
        result = self.service.stop({"run_id": handle.run_id, "wait": True, "timeout": 1})
        self.assertTrue(released.is_set())
        self.assertEqual(result["session_name"], "logical_session")

    def test_completed_run_can_be_renamed_and_dismissed(self):
        handle = self.manager.create(self.root)
        handle.state.update({"running": False, "session_name": "demo_session"})

        self.service.rename_session("demo_session", "教学项目修复")
        self.assertEqual(handle.state["session_title"], "教学项目修复")
        result = self.service.dismiss({"run_id": handle.run_id})

        self.assertTrue(result["dismissed"])
        self.assertIsNone(self.manager.get(handle.run_id))

    def test_running_run_must_be_stopped_before_dismiss(self):
        handle = self._running()
        with self.assertRaises(InteractiveExecutionError) as raised:
            self.service.dismiss({"run_id": handle.run_id})
        self.assertEqual(raised.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
