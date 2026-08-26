from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from harness import Session
from pipeline_engine import PipelineRunner
from run_coordinator import DurableRunQueue, DurableRunWorker


class DeterministicHarness:
    def __init__(self, root: Path):
        self.dir = root
        self.workspace = root
        self.name = "queued-test"
        self.config = {
            "name": self.name,
            "pipeline": {
                "start": "copy",
                "nodes": {
                    "copy": {
                        "op": "数据",
                        "action": "set",
                        "key": "answer",
                        "value": "$ctx.input",
                        "edges": [{"condition": "default", "to": "checkpoint"}],
                    },
                    "checkpoint": {
                        "op": "检查点",
                        "action": "save",
                        "label": "queued",
                        "edges": [{"condition": "checkpoint_saved", "to": "done"}],
                    },
                    "done": {"op": "结束", "inputs": {"value": "$ctx.answer"}, "edges": []},
                },
            },
        }
        self.agents = {}
        self.prompts = {}
        self.session = Session(workspace=root, save_dir=None)
        self.parent = None
        self.children = []
        self.slots = {}
        self.return_mode = "last"
        self._non_interactive = True


class DurableRunQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = DurableRunQueue(self.root / "runs.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_atomic_claim_and_dedupe(self):
        first = self.queue.enqueue({"input": "one"}, dedupe_key="same")
        duplicate = self.queue.enqueue({"input": "different"}, dedupe_key="same")
        self.assertEqual(first.id, duplicate.id)
        claims = []
        lock = threading.Lock()

        def claim(index):
            record = self.queue.claim(f"worker-{index}", lease_seconds=2)
            if record:
                with lock:
                    claims.append(record)

        threads = [threading.Thread(target=claim, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].attempts, 1)

    def test_expired_lease_is_reclaimed_with_checkpoint(self):
        queued = self.queue.enqueue({"input": "resume"}, max_attempts=3)
        first = self.queue.claim("dead-worker", lease_seconds=0.1)
        self.assertEqual(first.id, queued.id)
        self.assertTrue(self.queue.set_checkpoint(first.id, "dead-worker", "checkpoint.json"))
        time.sleep(0.15)

        reclaimed = self.queue.claim("replacement-worker", lease_seconds=2)

        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed.id, queued.id)
        self.assertEqual(reclaimed.attempts, 2)
        self.assertEqual(reclaimed.checkpoint_path, "checkpoint.json")
        self.assertEqual(reclaimed.lease_owner, "replacement-worker")

    def test_inflight_checkpoint_requires_inspect_then_confirmed_resume_or_discard(self):
        checkpoint = self.root / "inflight.json"
        checkpoint.write_text(json.dumps({
            "version": 3,
            "phase": "in_flight",
            "node": "process",
            "next_node": "process",
            "operation": "进程",
            "pending_approvals": {},
            "revisions": {"workspace": {"digest": "saved", "files": {}}},
        }), encoding="utf-8")
        queued = self.queue.enqueue({"input": "resume"}, max_attempts=3)
        running = self.queue.claim("lost-worker", lease_seconds=0.1)
        self.assertTrue(self.queue.set_checkpoint(running.id, "lost-worker", str(checkpoint)))
        time.sleep(0.15)

        self.assertIsNone(self.queue.claim("replacement", lease_seconds=1))
        interrupted = self.queue.get(queued.id)
        self.assertEqual(interrupted.status, "interrupted")
        preview = self.queue.checkpoint_preview(queued.id)
        self.assertEqual(preview["phase"], "in_flight")
        self.assertEqual(preview["node"], "process")
        with self.assertRaisesRegex(ValueError, "confirm_in_doubt"):
            self.queue.recover(queued.id, "resume")

        resumed = self.queue.recover(queued.id, "resume", confirm_in_doubt=True)
        self.assertEqual(resumed.status, "queued")
        self.assertTrue(resumed.payload["allow_inflight_resume"])

        connection = self.queue._connect()
        try:
            connection.execute("UPDATE runs SET status = 'interrupted' WHERE id = ?", (queued.id,))
        finally:
            connection.close()
        discarded = self.queue.recover(queued.id, "discard")
        self.assertEqual(discarded.status, "cancelled")

    def test_startup_recovery_resumes_completed_checkpoint_and_flags_unknown_work(self):
        completed_path = self.root / "completed.json"
        completed_path.write_text(json.dumps({"version": 3, "phase": "completed", "next_node": "done"}), encoding="utf-8")
        completed = self.queue.enqueue({"input": "completed"})
        completed_running = self.queue.claim("old-server-a", lease_seconds=30)
        self.assertTrue(self.queue.set_checkpoint(completed_running.id, "old-server-a", str(completed_path)))

        unknown = self.queue.enqueue({"input": "unknown"})
        unknown_running = self.queue.claim("old-server-b", lease_seconds=30)
        self.assertEqual(unknown_running.id, unknown.id)

        self.assertEqual(self.queue.recover_startup(), 2)
        self.assertEqual(self.queue.get(completed.id).status, "queued")
        self.assertEqual(self.queue.get(unknown.id).status, "interrupted")

    def test_running_cancel_is_cooperative_and_durable(self):
        queued = self.queue.enqueue({"input": "cancel"})
        running = self.queue.claim("worker", lease_seconds=2)
        self.assertEqual(running.id, queued.id)

        requested = self.queue.cancel(queued.id)

        self.assertTrue(requested.cancel_requested)
        self.assertEqual(requested.status, "running")
        self.assertFalse(self.queue.heartbeat(queued.id, "worker", lease_seconds=2))
        self.assertTrue(self.queue.acknowledge_cancel(queued.id, "worker"))
        self.assertEqual(self.queue.get(queued.id).status, "cancelled")

    def test_pause_and_resume_work_for_queued_and_running_runs(self):
        queued = self.queue.enqueue({"input": "pause"})
        paused = self.queue.pause(queued.id)
        self.assertEqual(paused.status, "paused")
        self.assertFalse(paused.pause_requested)
        resumed = self.queue.resume(queued.id)
        self.assertEqual(resumed.status, "queued")

        running = self.queue.claim("pause-worker", lease_seconds=2)
        self.assertEqual(running.id, queued.id)
        requested = self.queue.pause(queued.id)
        self.assertEqual(requested.status, "running")
        self.assertTrue(requested.pause_requested)
        self.assertTrue(self.queue.is_pause_requested(queued.id, "pause-worker"))
        self.assertTrue(self.queue.acknowledge_pause(queued.id, "pause-worker"))
        self.assertEqual(self.queue.get(queued.id).status, "paused")
        self.assertEqual(self.queue.resume(queued.id).status, "queued")

    def test_worker_executes_pipeline_runner_and_persists_ordered_events(self):
        queued = self.queue.enqueue({"input": {"typed": True}}, max_attempts=1)

        def execute(record, emit, cancelled):
            harness = DeterministicHarness(self.root)
            context = PipelineRunner(
                harness,
                initial_data=record.payload,
                on_output=emit,
                is_running=lambda: not cancelled(),
            ).run()
            return {"value": context.result, "stats": context.stats.as_dict()}

        worker = DurableRunWorker(self.queue, execute, owner="local-worker", lease_seconds=1)
        self.assertTrue(worker.run_once())

        finished = self.queue.get(queued.id)
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(finished.result["value"], {"typed": True})
        self.assertTrue(finished.checkpoint_path)
        self.assertTrue(Path(finished.checkpoint_path).is_file())
        events = self.queue.events(queued.id)
        self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
        self.assertIn("node_enter", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "run_succeeded")

    def test_worker_failure_is_retried_with_attempt_budget(self):
        queued = self.queue.enqueue({"input": "retry"}, max_attempts=2)
        calls = []

        def execute(record, _emit, _cancelled):
            calls.append(record.attempts)
            if len(calls) == 1:
                raise RuntimeError("transient failure")
            return {"ok": True}

        worker = DurableRunWorker(self.queue, execute, owner="retry-worker", lease_seconds=1)
        self.assertTrue(worker.run_once())
        self.assertEqual(self.queue.get(queued.id).status, "queued")
        time.sleep(1.05)
        self.assertTrue(worker.run_once())

        finished = self.queue.get(queued.id)
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(finished.attempts, 2)
        self.assertEqual(calls, [1, 2])

    def test_worker_observes_cancel_and_event_payloads_are_redacted(self):
        queued = self.queue.enqueue({"input": "wait", "api_key": "do-not-return"})
        entered = threading.Event()

        def execute(_record, emit, cancelled):
            emit("provider", {"Authorization": "Bearer secret", "safe": "visible"})
            entered.set()
            while not cancelled():
                time.sleep(0.01)
            raise RuntimeError("cancelled by test")

        worker = DurableRunWorker(self.queue, execute, owner="cancel-worker", lease_seconds=1)
        thread = threading.Thread(target=worker.run_once)
        thread.start()
        self.assertTrue(entered.wait(2))
        self.queue.cancel(queued.id)
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(self.queue.get(queued.id).status, "cancelled")
        self.assertEqual(self.queue.get(queued.id).as_dict()["payload"]["api_key"], "[REDACTED]")
        provider_event = next(event for event in self.queue.events(queued.id) if event["event"] == "provider")
        self.assertEqual(provider_event["payload"]["Authorization"], "[REDACTED]")
        self.assertEqual(provider_event["payload"]["safe"], "visible")

    def test_server_can_fork_completed_checkpoint_into_independent_workspace(self):
        from harness_editor import server as server_module

        source = self.root / "source"
        source.mkdir()
        (source / "answer.txt").write_text("fork me", encoding="utf-8")
        checkpoint = source / ".egoagent" / "checkpoints" / "source.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text(json.dumps({
            "version": 3, "phase": "completed", "run_id": "old", "next_node": None,
            "data": {"_run_id": "old"}, "messages": [], "full_messages": [],
        }), encoding="utf-8")
        original = self.queue.enqueue({
            "workspace": str(source), "source_workspace": str(source),
            "harness": "react_single", "identity": "dante", "messages": [],
        })
        running = self.queue.claim("fork-source", lease_seconds=2)
        self.assertTrue(self.queue.set_checkpoint(running.id, "fork-source", str(checkpoint)))
        self.assertTrue(self.queue.complete(running.id, "fork-source", {"result": "old", "stats": {}}))

        previous_queue = server_module._durable_run_queue
        server_module._durable_run_queue = self.queue
        try:
            forked = server_module._fork_durable_run(self.queue.get(original.id), from_checkpoint=True)
            fork_record = self.queue.get(forked.id)
            self.assertNotEqual(fork_record.payload["workspace"], str(source))
            self.assertEqual(Path(fork_record.payload["workspace"]).joinpath("answer.txt").read_text(encoding="utf-8"), "fork me")
            rewritten = json.loads(Path(fork_record.payload["resume_from"]).read_text(encoding="utf-8"))
            self.assertEqual(rewritten["run_id"], forked.id)
            self.assertEqual(rewritten["data"]["_run_id"], forked.id)
            self.assertEqual(self.queue.events(forked.id)[0]["event"], "run_forked")
        finally:
            server_module._durable_run_queue = previous_queue

    def test_run_comparison_reports_path_output_cost_and_mutations(self):
        from harness_editor.server import _compare_durable_runs

        records = []
        for index, output in enumerate(("left", "right")):
            queued = self.queue.enqueue({"case": index})
            running = self.queue.claim(f"compare-{index}", lease_seconds=2)
            self.queue.append_event(queued.id, "node_enter", {"node_id": "start", "op": "Agent", "agent": "coder"})
            if index:
                self.queue.append_event(queued.id, "node_enter", {"node_id": "review", "op": "Agent", "agent": "reviewer"})
                self.queue.append_event(queued.id, "tool", {"name": "modify_harness", "node_id": "review", "result": "changed"})
            self.assertTrue(self.queue.complete(queued.id, running.lease_owner, {
                "result": output,
                "stats": {"cost_actual": index + 1, "input_tokens_actual": 10 + index, "node_steps": index + 1},
            }))
            records.append(self.queue.get(queued.id))

        compared = _compare_durable_runs(records[0], records[1], self.queue)
        self.assertFalse(compared["same_output"])
        self.assertEqual(compared["path"]["common_prefix"], 1)
        self.assertEqual(compared["path"]["right_only"][0]["node_id"], "review")
        self.assertEqual(compared["delta"]["cost_actual"], 1)
        self.assertEqual(compared["right"]["mutations"][0]["tool"], "modify_harness")

    def test_http_api_enqueues_reads_and_cancels_a_durable_run(self):
        from harness_editor import server as server_module

        previous_queue = server_module._durable_run_queue
        server_module._durable_run_queue = self.queue
        httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            body = json.dumps(
                {
                    "harness": "react_single",
                    "identity": "dante",
                    "messages": [{"role": "user", "content": "queued"}],
                    "dedupe_key": "http-test",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                f"{base}/api/runs",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("harness_editor.server._start_durable_run_worker", return_value=None):
                with urllib.request.urlopen(request, timeout=5) as response:
                    created = json.loads(response.read())
                    self.assertEqual(response.status, 202)

            with urllib.request.urlopen(f"{base}/api/runs/{created['id']}", timeout=5) as response:
                fetched = json.loads(response.read())
            self.assertEqual(fetched["status"], "queued")
            self.assertEqual(fetched["payload"]["messages"][0]["content"], "queued")

            cancel_request = urllib.request.Request(
                f"{base}/api/runs/{created['id']}/cancel", data=b"{}", method="POST"
            )
            with urllib.request.urlopen(cancel_request, timeout=5) as response:
                cancelled = json.loads(response.read())
            self.assertEqual(cancelled["status"], "cancelled")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server_module._durable_run_queue = previous_queue

    def test_http_api_lists_inspects_and_recovers_interrupted_runs(self):
        from harness_editor import server as server_module

        checkpoint = self.root / "http-inflight.json"
        checkpoint.write_text(json.dumps({
            "version": 3, "phase": "in_flight", "node": "tool", "operation": "工具",
            "completed_steps": [{"node": "model"}], "artifacts": ["report.json"],
        }), encoding="utf-8")
        queued = self.queue.enqueue({"input": "http recovery"})
        running = self.queue.claim("gone", lease_seconds=30)
        self.assertTrue(self.queue.set_checkpoint(running.id, "gone", str(checkpoint)))
        connection = self.queue._connect()
        try:
            connection.execute(
                "UPDATE runs SET status = 'interrupted', lease_owner = NULL, lease_expires_at = NULL WHERE id = ?",
                (queued.id,),
            )
        finally:
            connection.close()

        previous_queue = server_module._durable_run_queue
        server_module._durable_run_queue = self.queue
        httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with urllib.request.urlopen(f"{base}/api/runs/recovery", timeout=5) as response:
                recovery = json.loads(response.read())
            self.assertEqual(recovery["runs"][0]["id"], queued.id)
            self.assertEqual(recovery["runs"][0]["checkpoint"]["phase"], "in_flight")

            with urllib.request.urlopen(f"{base}/api/runs/{queued.id}", timeout=5) as response:
                inspected = json.loads(response.read())
            self.assertEqual(inspected["checkpoint"]["artifacts"], ["report.json"])

            denied_request = urllib.request.Request(
                f"{base}/api/runs/{queued.id}/resume",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(denied_request, timeout=5)
            self.assertEqual(denied.exception.code, 409)

            resume_request = urllib.request.Request(
                f"{base}/api/runs/{queued.id}/resume",
                data=json.dumps({"confirm_in_doubt": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("harness_editor.server._start_durable_run_worker", return_value=None):
                with urllib.request.urlopen(resume_request, timeout=5) as response:
                    resumed = json.loads(response.read())
            self.assertEqual(resumed["status"], "queued")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server_module._durable_run_queue = previous_queue

    def test_server_worker_callback_runs_real_harness_builder_without_model_call(self):
        from harness_editor import server as server_module

        harness_root = self.root / "harness"
        smoke_dir = harness_root / "queue_smoke"
        smoke_dir.mkdir(parents=True)
        config = DeterministicHarness(self.root).config
        (smoke_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        previous_harness_dir = server_module.HARNESS_DIR
        previous_queue = server_module._durable_run_queue
        server_module.HARNESS_DIR = harness_root
        server_module._durable_run_queue = self.queue
        try:
            queued = self.queue.enqueue(
                {
                    "harness": "queue_smoke",
                    "identity": "dante",
                    "messages": [],
                    "initial_data": {"input": ["typed", 7]},
                },
                max_attempts=1,
            )
            worker = DurableRunWorker(
                self.queue,
                server_module._execute_durable_run,
                owner="server-callback-worker",
                lease_seconds=2,
            )

            self.assertTrue(worker.run_once())

            finished = self.queue.get(queued.id)
            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.result["result"], ["typed", 7])
            self.assertTrue(finished.result["checkpoint_path"])
        finally:
            server_module.HARNESS_DIR = previous_harness_dir
            server_module._durable_run_queue = previous_queue


if __name__ == "__main__":
    unittest.main()
