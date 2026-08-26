import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from capability_reference import build_capability_snapshot, source_reference
from capability_registry import CapabilityRegistry
from harness import Session, runtime_scope
from trajectory import TrajectoryReader


class CapabilityReferenceTests(unittest.TestCase):
    def test_registry_id_is_stable_while_source_revision_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identity" / "coder"
            identity.mkdir(parents=True)
            metadata = identity / "id.json"
            metadata.write_text(json.dumps({"name": "coder", "description": "first"}), encoding="utf-8")
            registry = CapabilityRegistry(root, embedding_backend=False)
            registry.reindex()
            before = next(item for item in registry.list() if item["name"] == "coder")

            metadata.write_text(json.dumps({"name": "coder", "description": "changed"}), encoding="utf-8")
            registry.reindex()
            after = registry.get(before["id"])

            self.assertEqual(before["id"], after["id"])
            self.assertNotEqual(before["ref"]["digest"], after["ref"]["digest"])
            self.assertNotEqual(before["ref"]["revision"], after["ref"]["revision"])

    def test_model_calls_reference_one_deduplicated_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity_path = root / "identity" / "coder"
            tool_path = root / "tool" / "search"
            identity_path.mkdir(parents=True)
            tool_path.mkdir(parents=True)
            (identity_path / "id.json").write_text('{"name":"coder"}', encoding="utf-8")
            (tool_path / "meta.json").write_text('{"name":"search"}', encoding="utf-8")
            snapshot = build_capability_snapshot(
                agent="coder",
                identity=source_reference(kind="identity", name="coder", path=identity_path),
                capabilities=[source_reference(kind="tool", name="search", path=tool_path)],
            )

            class FakeAgent:
                name = "coder"
                identity = SimpleNamespace(identity_path=identity_path)

                @staticmethod
                def capability_snapshot():
                    return snapshot

            session = Session(workspace=root, save_dir=root / "session")
            harness = SimpleNamespace(name="demo", agents={"coder": FakeAgent()}, session=session)
            with runtime_scope(harness=harness):
                first = session.begin_model_call(messages=[], tools=[], agent="coder")
                session.finish_model_call(first, agent="coder", content="one")
                second = session.begin_model_call(messages=[], tools=[], agent="coder")
                session.finish_model_call(second, agent="coder", content="two")

            events = TrajectoryReader(root / "session" / "trajectory.jsonl").read_all()
            snapshots = [event for event in events if event["type"] == "capability.snapshot"]
            requests = [event for event in events if event["type"] == "model.request"]
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["category"], "capability")
            self.assertEqual(
                [event["data"]["capability_snapshot_id"] for event in requests],
                [snapshot["snapshot_id"], snapshot["snapshot_id"]],
            )


if __name__ == "__main__":
    unittest.main()
