import threading
import unittest

from port_graph import PortBlockResult, PortGraphError, PortGraphRunner, normalize_port_graph


class PortGraphRunnerTests(unittest.TestCase):
    def run_graph(self, graph, executor, **kwargs):
        return PortGraphRunner(graph, executor, **kwargs).run()

    def test_repeated_dynamic_outputs_create_repeated_downstream_executions(self):
        graph = {
            "blocks": {
                "source": {},
                "sink": {"required_inputs": ["item"]},
            },
            "links": [
                {"source_id": "source", "source_name": "item", "sink_id": "sink", "sink_name": "item"},
            ],
        }

        result = self.run_graph(
            graph,
            lambda block, inputs: (
                PortBlockResult([("item", 1), ("item", 2)])
                if block["id"] == "source"
                else PortBlockResult([("output", inputs["item"] * 10)])
            ),
        )

        self.assertEqual(result["status"], "completed")
        sink_runs = [item for item in result["executions"] if item["block_id"] == "sink"]
        self.assertEqual([item["inputs"]["item"] for item in sink_runs], [1, 2])
        self.assertCountEqual([item["value"] for item in result["terminal_outputs"]], [10, 20])

    def test_static_output_is_reused_by_every_dynamic_execution(self):
        graph = {
            "blocks": {
                "settings": {},
                "items": {},
                "worker": {"required_inputs": ["item", "config"]},
            },
            "links": [
                {"source_id": "settings", "source_name": "config", "sink_id": "worker", "sink_name": "config", "is_static": True},
                {"source_id": "items", "source_name": "item", "sink_id": "worker", "sink_name": "item"},
            ],
        }

        def execute(block, inputs):
            if block["id"] == "settings":
                return PortBlockResult([("config", {"prefix": "v"})])
            if block["id"] == "items":
                return PortBlockResult([("item", 1), ("item", 2), ("item", 3)])
            return PortBlockResult([("output", f"{inputs['config']['prefix']}{inputs['item']}")])

        result = self.run_graph(graph, execute)

        worker_runs = [item for item in result["executions"] if item["block_id"] == "worker"]
        self.assertEqual(len(worker_runs), 3)
        self.assertTrue(all(item["inputs"]["config"] == {"prefix": "v"} for item in worker_runs))
        self.assertEqual(sorted(item["value"] for item in result["terminal_outputs"]), ["v1", "v2", "v3"])
        self.assertEqual(result["static_values"][0]["port"], "config")

    def test_dynamic_fan_in_pairs_events_in_arrival_order(self):
        graph = {
            "blocks": {"left": {}, "right": {}, "join": {"required_inputs": ["a", "b"]}},
            "links": [
                {"source_id": "left", "source_name": "value", "sink_id": "join", "sink_name": "a"},
                {"source_id": "right", "source_name": "value", "sink_id": "join", "sink_name": "b"},
            ],
        }

        def execute(block, inputs):
            if block["id"] == "left":
                return PortBlockResult([("value", "a1"), ("value", "a2")])
            if block["id"] == "right":
                return PortBlockResult([("value", "b1"), ("value", "b2")])
            return PortBlockResult([("pair", [inputs["a"], inputs["b"]])])

        result = self.run_graph(graph, execute)

        pairs = [item["value"] for item in result["terminal_outputs"]]
        self.assertCountEqual(pairs, [["a1", "b1"], ["a2", "b2"]])

    def test_cycles_are_allowed_but_bounded_by_events(self):
        graph = {
            "blocks": {"start": {}, "increment": {"required_inputs": ["value"]}},
            "links": [
                {"source_id": "start", "source_name": "value", "sink_id": "increment", "sink_name": "value"},
                {"source_id": "increment", "source_name": "value", "sink_id": "increment", "sink_name": "value"},
            ],
            "max_events": 10,
        }

        def execute(block, inputs):
            if block["id"] == "start":
                return PortBlockResult([("value", 0)])
            value = inputs["value"] + 1
            return PortBlockResult([] if value == 3 else [("value", value)])

        result = self.run_graph(graph, execute)

        values = [item["inputs"]["value"] for item in result["executions"] if item["block_id"] == "increment"]
        self.assertEqual(values, [0, 1, 2])
        self.assertEqual(result["status"], "completed")

    def test_event_limit_stops_an_unbounded_cycle(self):
        graph = {
            "blocks": {"start": {}, "again": {"required_inputs": ["value"]}},
            "links": [
                {"source_id": "start", "source_name": "value", "sink_id": "again", "sink_name": "value"},
                {"source_id": "again", "source_name": "value", "sink_id": "again", "sink_name": "value"},
            ],
            "max_events": 2,
        }

        result = self.run_graph(
            graph,
            lambda block, inputs: PortBlockResult([("value", 0 if block["id"] == "start" else inputs["value"] + 1)]),
        )

        self.assertEqual(result["status"], "limit_exceeded")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["errors"][0]["type"], "PortGraphLimitError")

    def test_cancellation_prevents_newly_ready_execution_from_starting(self):
        state = {"running": True}
        calls = []
        graph = {
            "blocks": {"source": {}, "sink": {"required_inputs": ["value"]}},
            "links": [
                {"source_id": "source", "sink_id": "sink", "sink_name": "value"},
            ],
        }

        def execute(block, _inputs):
            calls.append(block["id"])
            return "ready"

        def on_event(name, _payload):
            if name == "port_output":
                state["running"] = False

        result = self.run_graph(
            graph, execute, is_running=lambda: state["running"], on_event=on_event,
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(calls, ["source"])
        sink = next(item for item in result["executions"] if item["block_id"] == "sink")
        self.assertEqual(sink["status"], "cancelled")

    def test_resume_keeps_execution_ids_and_does_not_repeat_completed_source(self):
        state = {"running": True}
        snapshot = {}
        first_calls = []
        graph = {
            "blocks": {"source": {}, "sink": {"required_inputs": ["value"]}},
            "links": [
                {"source_id": "source", "sink_id": "sink", "sink_name": "value"},
            ],
        }

        def stop_after_delivery(name, _payload):
            if name == "port_output":
                state["running"] = False

        def capture(value):
            snapshot.clear()
            snapshot.update(value)

        first = self.run_graph(
            graph,
            lambda block, _inputs: first_calls.append(block["id"]) or "persisted",
            is_running=lambda: state["running"],
            on_event=stop_after_delivery,
            on_state=capture,
        )
        self.assertEqual(first["status"], "cancelled")
        source_id = next(item["id"] for item in first["executions"] if item["block_id"] == "source")
        sink_id = next(item["id"] for item in first["executions"] if item["block_id"] == "sink")

        resumed_calls = []
        resumed = self.run_graph(
            graph,
            lambda block, inputs: resumed_calls.append(block["id"]) or f"used:{inputs['value']}",
            initial_state=snapshot,
        )

        self.assertEqual(resumed["status"], "completed")
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed_calls, ["sink"])
        self.assertEqual([item["id"] for item in resumed["executions"]], [source_id, sink_id])
        self.assertEqual(len([item for item in resumed["events"] if item["block_id"] == "source"]), 1)
        self.assertEqual(resumed["terminal_outputs"][-1]["value"], "used:persisted")

    def test_independent_ready_blocks_execute_concurrently(self):
        lock = threading.Lock()
        overlap = threading.Event()
        running = 0
        peak = 0

        def execute(_block, _inputs):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
                if running >= 2:
                    overlap.set()
            overlap.wait(timeout=2)
            with lock:
                running -= 1
            return "done"

        result = self.run_graph(
            {"blocks": {"a": {}, "b": {}, "c": {}}, "links": [], "max_workers": 3},
            execute,
        )

        self.assertEqual(result["counts"]["completed"], 3)
        self.assertGreaterEqual(peak, 2)

    def test_non_fail_fast_error_can_route_to_a_recovery_block(self):
        graph = {
            "blocks": {"bad": {"error_port": "error"}, "recover": {"required_inputs": ["error"]}},
            "links": [
                {"source_id": "bad", "source_name": "error", "sink_id": "recover", "sink_name": "error"},
            ],
            "fail_fast": False,
        }

        def execute(block, inputs):
            if block["id"] == "bad":
                raise ValueError("boom")
            return PortBlockResult([("output", inputs["error"]["message"])])

        result = self.run_graph(graph, execute)

        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(result["terminal_outputs"][0]["value"], "boom")
        self.assertEqual(result["counts"]["failed"], 1)

    def test_sensitive_review_can_edit_inputs_or_route_rejection(self):
        graph = {
            "blocks": {"approved": {"sensitive": True}, "rejected": {"sensitive": True}},
            "links": [],
            "initial_inputs": {"approved": {"value": "old"}, "rejected": {}},
        }

        def review(block, inputs):
            return {"approved": block["id"] == "approved", "data": {**inputs, "value": "edited"}}

        result = self.run_graph(graph, lambda _block, inputs: inputs["value"], review_block=review)

        approved = next(item for item in result["executions"] if item["block_id"] == "approved")
        rejected = next(item for item in result["executions"] if item["block_id"] == "rejected")
        self.assertEqual(approved["inputs"]["value"], "edited")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(result["counts"]["rejected"], 1)

    def test_input_and_output_schemas_are_enforced(self):
        graph = {
            "blocks": {
                "source": {"output_schema": {"type": "integer"}},
            },
            "links": [],
        }

        result = self.run_graph(graph, lambda _block, _inputs: "wrong")

        self.assertEqual(result["status"], "failed")
        self.assertIn("integer", result["errors"][0]["message"])

    def test_ambiguous_static_and_dynamic_sink_is_rejected(self):
        graph = {
            "blocks": {"a": {}, "b": {}, "sink": {"required_inputs": ["value"]}},
            "links": [
                {"source_id": "a", "sink_id": "sink", "sink_name": "value", "is_static": True},
                {"source_id": "b", "sink_id": "sink", "sink_name": "value"},
            ],
        }

        with self.assertRaisesRegex(PortGraphError, "mix static and dynamic"):
            normalize_port_graph(graph)


if __name__ == "__main__":
    unittest.main()
