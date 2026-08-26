import tempfile
import threading
import unittest
from pathlib import Path

from interactive_runs import InteractiveRunManager


class InteractiveRunManagerTests(unittest.TestCase):
    def test_run_state_queues_and_debug_controls_are_isolated(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            manager = InteractiveRunManager()
            first = manager.create(first_dir)
            second = manager.create(second_dir)

            first.state.update({"running": True, "harness": "first"})
            second.state.update({"running": True, "harness": "second"})
            first.input_queue.put("first input")
            second.input_queue.put("second input")
            first.step_budget = 1
            second.node_directive = {"action": "skip", "node_id": "n2"}

            self.assertNotEqual(first.run_id, second.run_id)
            self.assertEqual(first.input_queue.get_nowait(), "first input")
            self.assertEqual(second.input_queue.get_nowait(), "second input")
            self.assertEqual(first.step_budget, 1)
            self.assertIsNone(first.node_directive)
            self.assertEqual(second.step_budget, 0)
            self.assertEqual(second.node_directive["node_id"], "n2")
            self.assertEqual(manager.resolve(run_id=first.run_id), first)
            self.assertEqual(manager.latest(second_dir), second)

    def test_context_binding_selects_the_correct_parallel_run(self):
        with tempfile.TemporaryDirectory() as workspace:
            manager = InteractiveRunManager()
            first = manager.create(workspace)
            second = manager.create(workspace)
            observed = []

            def worker(handle):
                with manager.bind(handle):
                    observed.append(manager.current().run_id)

            threads = [
                threading.Thread(target=worker, args=(first,)),
                threading.Thread(target=worker, args=(second,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertCountEqual(observed, [first.run_id, second.run_id])
            self.assertIsNone(manager.current())

    def test_snapshots_are_detached_and_running_runs_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as workspace:
            manager = InteractiveRunManager()
            handle = manager.create(Path(workspace))
            handle.state["running"] = True
            handle.outputs.append({"agent": "coder", "text": "original"})
            snapshot = handle.snapshot(include_outputs=True)
            snapshot["outputs"][0]["text"] = "changed"

            self.assertEqual(handle.outputs[0]["text"], "original")
            self.assertEqual(snapshot["created_at"], handle.created_at)
            self.assertEqual(snapshot["touched_at"], handle.touched_at)
            self.assertIn("change_transaction_id", snapshot)
            with self.assertRaises(RuntimeError):
                manager.remove(handle.run_id)
            handle.state["running"] = False
            self.assertIs(manager.remove(handle.run_id), handle)
            self.assertIsNone(manager.get(handle.run_id))


if __name__ == "__main__":
    unittest.main()
