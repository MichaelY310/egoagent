from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import (
    Session,
    get_current_harness,
    get_current_run_context,
    get_output_callback,
    runtime_scope,
)
from pipeline_engine import PipelineRunner, RunContext
from harness_editor.change_tracker import get_active_transaction, transaction_scope
from llm.env_config import SecretView


class FakeHarness:
    def __init__(self, root: Path):
        self.dir = root
        self.workspace = root
        self.name = "runtime-isolation"
        self.config = {
            "name": self.name,
            "pipeline": {
                "start": "end",
                "max_steps": 2,
                "nodes": {
                    "end": {
                        "id": "end",
                        "op": "结束",
                        "inputs": {"value": "ok"},
                        "edges": [],
                    }
                },
            },
        }
        self.session = Session(workspace=root, save_dir=None)
        self.agents = {}
        self.parent = None


def make_context(harness: FakeHarness, *, is_running=lambda: True) -> RunContext:
    return RunContext(
        harness=harness,
        graph=harness.config["pipeline"],
        on_output=lambda _event, _payload: None,
        get_input=lambda: None,
        is_running=is_running,
    )


class RuntimeScopeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_nested_scope_restores_exact_outer_values(self):
        outer_harness = FakeHarness(self.root)
        inner_harness = FakeHarness(self.root)
        outer_context = make_context(outer_harness)
        outer_callback = object()

        self.assertIsNone(get_current_harness())
        self.assertIsNone(get_output_callback())
        self.assertIsNone(get_current_run_context())
        with runtime_scope(
            harness=outer_harness,
            output_callback=outer_callback,
            run_context=outer_context,
        ):
            with runtime_scope(harness=inner_harness):
                self.assertIs(get_current_harness(), inner_harness)
                self.assertIs(get_output_callback(), outer_callback)
                self.assertIs(get_current_run_context(), outer_context)
            self.assertIs(get_current_harness(), outer_harness)
            self.assertIs(get_output_callback(), outer_callback)
            self.assertIs(get_current_run_context(), outer_context)

        self.assertIsNone(get_current_harness())
        self.assertIsNone(get_output_callback())
        self.assertIsNone(get_current_run_context())

    def test_parallel_threads_do_not_share_runtime_state(self):
        barrier = threading.Barrier(3)
        failures: list[str] = []

        def worker(label: str) -> None:
            harness = FakeHarness(self.root)
            callback = object()
            context = make_context(harness)
            with runtime_scope(harness=harness, output_callback=callback, run_context=context):
                barrier.wait(timeout=5)
                if get_current_harness() is not harness:
                    failures.append(f"{label}: harness leaked")
                if get_output_callback() is not callback:
                    failures.append(f"{label}: callback leaked")
                if get_current_run_context() is not context:
                    failures.append(f"{label}: context leaked")
                barrier.wait(timeout=5)

        threads = [threading.Thread(target=worker, args=(label,)) for label in ("a", "b")]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(failures, failures)
        self.assertIsNone(get_current_harness())
        self.assertIsNone(get_current_run_context())

    def test_parent_registers_only_running_child_and_cancellation_cascades(self):
        parent_harness = FakeHarness(self.root)
        child_harness = FakeHarness(self.root)
        parent_context = make_context(parent_harness)
        entered = threading.Event()
        release = threading.Event()
        events: list[tuple[str, dict]] = []

        def before_node(_context, _node_id, _node):
            entered.set()
            release.wait(timeout=5)

        with runtime_scope(harness=parent_harness, run_context=parent_context):
            runner = PipelineRunner(
                child_harness,
                on_output=lambda event, payload: events.append((event, payload)),
                before_node=before_node,
            )

        self.assertEqual(parent_context._children, {})
        thread = threading.Thread(target=runner.run)
        thread.start()
        self.assertTrue(entered.wait(timeout=5))
        self.assertIs(parent_context._children[runner.ctx.run_id], runner.ctx)

        parent_context.cancel()
        release.set()
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertTrue(runner.ctx.cancel_event.is_set())
        self.assertEqual(parent_context._children, {})
        self.assertIn(runner.ctx.run_id, parent_context.child_run_ids)
        done = [payload for event, payload in events if event == "done"]
        self.assertEqual(done[-1]["status"], "cancelled")
        self.assertEqual(done[-1]["parent_run_id"], parent_context.run_id)

    def test_deadline_is_part_of_cooperative_cancellation(self):
        harness = FakeHarness(self.root)
        context = make_context(harness)
        context.deadline_monotonic = time.monotonic() - 0.001
        self.assertTrue(context.cancelled())

    def test_run_context_owns_workspace_session_sink_secrets_and_transaction(self):
        harness = FakeHarness(self.root)
        sink = lambda _event, _payload: None
        secret_view = SecretView(["ALLOWED"], {"ALLOWED": "value", "DENIED": "hidden"})
        context = RunContext(
            harness=harness,
            graph=harness.config["pipeline"],
            on_output=sink,
            get_input=lambda: None,
            is_running=lambda: True,
            secret_view=secret_view,
        )

        self.assertEqual(context.workspace, self.root.resolve())
        self.assertIs(context.session, harness.session)
        self.assertIs(context.event_sink, sink)
        self.assertEqual(context.secret_view.resolve("ALLOWED"), "value")
        self.assertNotIn("value", repr(context.secret_view))
        with self.assertRaises(PermissionError):
            context.secret_view.resolve("DENIED")
        self.assertEqual(context.change_transaction_id, f"run-{context.run_id}")

    def test_runner_binds_change_transaction_and_restores_outer_transaction(self):
        harness = FakeHarness(self.root)
        observed = []
        events = []
        runner = PipelineRunner(
            harness,
            on_output=lambda event, payload: events.append((event, payload)),
            before_node=lambda context, _node_id, _node: observed.append(
                (get_active_transaction(), context.change_transaction_id)
            ),
        )

        with transaction_scope("outer"):
            runner.run()
            self.assertEqual(get_active_transaction(), "outer")

        self.assertIsNone(get_active_transaction())
        self.assertEqual(observed, [(runner.ctx.change_transaction_id, runner.ctx.change_transaction_id)])
        started = next(payload for event, payload in events if event == "run_started")
        self.assertEqual(started["change_transaction_id"], runner.ctx.change_transaction_id)

    def test_cancelling_one_top_level_run_does_not_cancel_another(self):
        first = make_context(FakeHarness(self.root))
        second = make_context(FakeHarness(self.root))
        first.cancel()
        self.assertTrue(first.cancelled())
        self.assertFalse(second.cancelled())

    def test_child_inherits_the_earliest_parent_deadline(self):
        harness = FakeHarness(self.root)
        parent = make_context(harness)
        parent.deadline_monotonic = time.monotonic() + 60
        with runtime_scope(harness=harness, run_context=parent):
            child = PipelineRunner(FakeHarness(self.root), deadline_monotonic=time.monotonic() + 120)
        self.assertEqual(child.ctx.deadline_monotonic, parent.deadline_monotonic)

    def test_expired_parent_prevents_child_node_from_starting(self):
        harness = FakeHarness(self.root)
        parent = make_context(harness)
        parent.deadline_monotonic = time.monotonic() - 0.001
        started = []
        events = []
        with runtime_scope(harness=harness, run_context=parent):
            child = PipelineRunner(
                FakeHarness(self.root),
                before_node=lambda *_args: started.append(True),
                on_output=lambda event, payload: events.append((event, payload)),
            )

        child.run()

        self.assertEqual(started, [])
        done = [payload for event, payload in events if event == "done"]
        self.assertEqual(done[-1]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
