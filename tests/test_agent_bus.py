from __future__ import annotations

import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_bus import AgentBus
from pipeline_engine import PipelineError, PipelineRunner
from test_pipeline_runtime import FakeHarness


class AgentBusTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        self.bus = AgentBus(self.root / ".egoagent" / "agent-bus.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_subscriptions_idempotency_and_atomic_single_consumer_claim(self):
        self.bus.register("architect", identity="dante", subscriptions=["artifact.design"])
        self.bus.register("qa", identity="dante", subscriptions=["artifact.*"])
        first = self.bus.publish(
            topic="artifact.design",
            sender="product",
            payload={"modules": ["core"]},
            idempotency_key="design-v1",
        )
        duplicate = self.bus.publish(
            topic="artifact.design",
            sender="product",
            payload={"modules": ["different"]},
            idempotency_key="design-v1",
        )

        self.assertEqual(first["recipients"], ["architect", "qa"])
        self.assertEqual(duplicate["message_id"], first["message_id"])
        self.assertTrue(duplicate["deduplicated"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda owner: self.bus.receive(
                        agent_id="qa", owner=owner, limit=1, lease_seconds=5
                    ),
                    ["worker-a", "worker-b"],
                )
            )
        claimed = [message for batch in claims for message in batch]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["payload"], {"modules": ["core"]})
        self.assertEqual(self.bus.acknowledge(claimed)["acknowledged"], 1)
        self.assertEqual(self.bus.receive(agent_id="qa", owner="worker-c"), [])

        architect_claim = self.bus.receive(agent_id="architect", owner="architect-worker")
        self.assertEqual(len(architect_claim), 1)
        self.assertEqual(architect_claim[0]["message_id"], first["message_id"])

    def test_expired_lease_redelivers_then_reaches_dead_letter_limit(self):
        self.bus.register("worker", subscriptions=["task.*"])
        self.bus.publish(
            topic="task.code",
            sender="manager",
            payload={"task": "T1"},
            max_attempts=2,
        )

        # Keep enough headroom for a loaded Windows CI host to reopen SQLite and
        # renew the same lease before it expires.  Twenty milliseconds made the
        # intended same-owner-resume assertion depend on machine scheduling.
        first = self.bus.receive(agent_id="worker", owner="crashed", lease_seconds=0.25)
        self.assertEqual(first[0]["attempt"], 1)
        resumed = self.bus.receive(agent_id="worker", owner="crashed", lease_seconds=0.25)
        self.assertEqual(resumed[0]["message_id"], first[0]["message_id"])
        self.assertEqual(resumed[0]["attempt"], 1)
        time.sleep(0.35)
        second = self.bus.receive(agent_id="worker", owner="replacement", lease_seconds=1)
        self.assertEqual(second[0]["attempt"], 2)
        outcome = self.bus.reject(second, error="verification failed")

        self.assertEqual(outcome, {"retried": 0, "dead": 1, "requested": 1})
        self.assertEqual(self.bus.receive(agent_id="worker", owner="third"), [])
        dead = self.bus.list_messages(recipient="worker", state="dead")
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["last_error"], "verification failed")

    def test_existing_data_node_runs_cross_role_handoff_without_new_component(self):
        graph = {
            "start": "register_product",
            "nodes": {
                "register_product": {
                    "op": "数据",
                    "action": "agent_register",
                    "agent_id": "product:${ctx._run_id}",
                    "identity": "dante",
                    "edges": [{"condition": "agent_registered", "to": "register_qa"}],
                },
                "register_qa": {
                    "op": "数据",
                    "action": "agent_register",
                    "agent_id": "qa:${ctx._run_id}",
                    "subscriptions": ["artifact.${ctx._run_id}.*"],
                    "edges": [{"condition": "agent_registered", "to": "publish"}],
                },
                "publish": {
                    "op": "数据",
                    "action": "message_publish",
                    "topic": "artifact.${ctx._run_id}.prd",
                    "sender": "product:${ctx._run_id}",
                    "payload": {"acceptance": ["tests pass"]},
                    "idempotency_key": "${ctx._run_id}:prd",
                    "edges": [{"condition": "message_published", "to": "receive"}],
                },
                "receive": {
                    "op": "数据",
                    "action": "message_receive",
                    "agent_id": "qa:${ctx._run_id}",
                    "topics": ["artifact.${ctx._run_id}.*"],
                    "limit": 10,
                    "output_var": "qa_inbox",
                    "edges": [{"condition": "messages_received", "to": "ack"}],
                },
                "ack": {
                    "op": "数据",
                    "action": "message_ack",
                    "receipts": "$ctx.qa_inbox",
                    "edges": [{"condition": "messages_acknowledged", "to": "done"}],
                },
                "done": {"op": "结束", "value": "$ctx.qa_inbox", "edges": []},
            },
        }
        harness = FakeHarness(self.root, graph)
        result = PipelineRunner(harness).run()

        self.assertEqual(result.result[0]["payload"], {"acceptance": ["tests pass"]})
        self.assertEqual(result.result[0]["topic"], f"artifact.{result.run_id}.prd")
        rows = self.bus.list_messages(recipient=f"qa:{result.run_id}", state="acked")
        self.assertEqual(len(rows), 1)

    def test_data_node_confines_bus_database_to_workspace(self):
        graph = {
            "start": "escape",
            "nodes": {
                "escape": {
                    "op": "数据",
                    "action": "agent_list",
                    "path": "../outside.sqlite3",
                    "edges": [],
                }
            },
        }
        harness = FakeHarness(self.root, graph)
        with self.assertRaises(PipelineError):
            PipelineRunner(harness).run()


if __name__ == "__main__":
    unittest.main()
