import copy
import json
import tempfile
import unittest
from pathlib import Path

from harness import Session
from session_branching import SessionBranchError, SessionBranchService
from trajectory import TrajectoryReader, messages_sha256


class FakeModel:
    model = "fake-merge-model"
    provider = "test"

    def __init__(self):
        self.calls = []

    def complete(self, messages, *, max_tokens, temperature):
        self.calls.append(copy.deepcopy(messages))
        return {
            "content": f"faithful result {len(self.calls)}",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            "model": self.model,
            "provider": self.provider,
        }


def append_message(session, role, content, name=None):
    message = {"role": role, "content": content}
    if name:
        message["name"] = name
    session.record(message)
    session.record_full(copy.deepcopy(message))


def create_session(root: Path, name: str, messages):
    session = Session(workspace=root, save_dir=root / name)
    for role, content in messages:
        append_message(session, role, content)
    session.save()
    return session


def append_to_saved(root: Path, name: str, role: str, content: str):
    session = Session(workspace=root)
    session.load(root / name)
    append_message(session, role, content)
    session.save()


class SessionBranchServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "sessions"
        self.root.mkdir()
        self.service = SessionBranchService(self.root, workspace=self.root.parent)

    def tearDown(self):
        self.temporary.cleanup()

    def test_fork_is_self_contained_and_does_not_modify_source(self):
        source = create_session(self.root, "source", [("user", "hello"), ("assistant", "world")])
        source_hash = messages_sha256(source.messages)
        source_trajectory = (self.root / "source" / "trajectory.jsonl").read_bytes()

        result = self.service.fork("source", destination_name="feature-a")

        self.assertEqual(result["session"], "feature-a")
        self.assertNotEqual(result["trace_id"], source.trajectory.trace_id)
        self.assertEqual((self.root / "source" / "trajectory.jsonl").read_bytes(), source_trajectory)
        fork = Session(workspace=self.root.parent)
        fork.load(self.root / "feature-a")
        self.assertEqual(messages_sha256(fork.messages), source_hash)
        lineage = json.loads((self.root / "feature-a" / "lineage.json").read_text(encoding="utf-8"))
        self.assertEqual(lineage["operation"], "fork")
        self.assertEqual(lineage["parents"][0]["name"], "source")
        reader = TrajectoryReader(self.root / "feature-a" / "trajectory.jsonl")
        self.assertTrue(reader.validate()["valid"])
        self.assertIn("session.forked", [event["type"] for event in reader.read_all()])

    def test_create_persists_an_empty_replayable_session(self):
        result = self.service.create(destination_name="new-work")
        self.assertEqual(result["operation"], "create")
        created = Session(workspace=self.root.parent)
        created.load(self.root / "new-work")
        self.assertEqual(created.messages, [])
        self.assertTrue((self.root / "new-work" / "session.json").is_file())
        self.assertIn("session.created", [event["type"] for event in TrajectoryReader(self.root / "new-work" / "trajectory.jsonl").read_all()])

    def test_direct_merge_appends_only_right_branch_delta(self):
        create_session(self.root, "base", [("user", "shared request")])
        self.service.fork("base", destination_name="left")
        self.service.fork("base", destination_name="right")
        append_to_saved(self.root, "left", "assistant", "left-only decision")
        append_to_saved(self.root, "right", "assistant", "right-only finding")

        result = self.service.merge("left", "right", mode="direct", destination_name="merged")

        self.assertEqual(result["common_messages"], 1)
        self.assertEqual(result["left_new_messages"], 1)
        self.assertEqual(result["right_new_messages"], 1)
        merged = Session(workspace=self.root.parent)
        merged.load(self.root / "merged")
        self.assertEqual(
            [message["content"] for message in merged.messages],
            ["shared request", "left-only decision", "right-only finding"],
        )
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(TrajectoryReader(self.root / "merged" / "trajectory.jsonl").validate()["valid"])

    def test_auto_uses_separate_summaries_when_delta_is_long(self):
        model = FakeModel()
        service = SessionBranchService(self.root, workspace=self.root.parent, model=model)
        create_session(self.root, "base", [("user", "shared")])
        service.fork("base", destination_name="left")
        service.fork("base", destination_name="right")
        append_to_saved(self.root, "left", "assistant", "A" * 1500)
        append_to_saved(self.root, "right", "assistant", "B" * 1500)

        result = service.merge("left", "right", mode="auto", threshold_tokens=256, destination_name="summarized")

        self.assertEqual(result["mode"], "summary")
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(len(model.calls), 2)
        merged = Session(workspace=self.root.parent)
        merged.load(self.root / "summarized")
        self.assertEqual([message.get("name") for message in merged.messages[-2:]], ["merge_summary_a", "merge_summary_b"])
        calls = TrajectoryReader(self.root / "summarized" / "trajectory.jsonl").model_calls()
        self.assertEqual([call["metadata"]["agent"] for call in calls], ["merge_summarizer_a", "merge_summarizer_b"])

    def test_dialogue_merge_keeps_agents_distinct_in_exact_trace(self):
        model = FakeModel()
        service = SessionBranchService(self.root, workspace=self.root.parent, model=model)
        create_session(self.root, "base", [("user", "shared")])
        service.fork("base", destination_name="left")
        service.fork("base", destination_name="right")
        append_to_saved(self.root, "left", "assistant", "implemented feature A")
        append_to_saved(self.root, "right", "assistant", "found conflict B")

        result = service.merge("left", "right", mode="dialogue", dialogue_rounds=2, destination_name="dialogue")

        self.assertEqual(result["model_calls"], 5)
        calls = TrajectoryReader(self.root / "dialogue" / "trajectory.jsonl").model_calls()
        self.assertEqual(
            [call["metadata"]["agent"] for call in calls],
            ["merge_branch_a", "merge_branch_b", "merge_branch_a", "merge_branch_b", "merge_synthesizer"],
        )
        merged = Session(workspace=self.root.parent)
        merged.load(self.root / "dialogue")
        self.assertEqual(merged.messages[-1]["name"], "merge_synthesis")
        self.assertTrue(TrajectoryReader(self.root / "dialogue" / "trajectory.jsonl").validate()["valid"])

    def test_rule_based_merge_many_deduplicates_shared_history(self):
        create_session(self.root, "base", [("user", "shared")])
        for name, content in (("one", "first"), ("two", "second"), ("three", "third")):
            self.service.fork("base", destination_name=name)
            append_to_saved(self.root, name, "assistant", content)

        result = self.service.merge_many(["one", "two", "three"], mode="direct", destination_name="all")

        self.assertEqual(result["parent_count"], 3)
        merged = Session(workspace=self.root.parent)
        merged.load(self.root / "all")
        self.assertEqual([message["content"] for message in merged.messages], ["shared", "first", "second", "third"])
        self.assertEqual([parent["name"] for parent in result["lineage"]["parents"]], ["one", "two", "three"])

    def test_dialogue_merge_many_records_each_branch_agent(self):
        model = FakeModel()
        service = SessionBranchService(self.root, workspace=self.root.parent, model=model)
        for name in ("one", "two", "three"):
            create_session(self.root, name, [("user", name)])

        result = service.merge_many(["one", "two", "three"], mode="dialogue", dialogue_rounds=1, destination_name="talk")

        self.assertEqual(result["model_calls"], 4)
        agents = [call["metadata"]["agent"] for call in TrajectoryReader(self.root / "talk" / "trajectory.jsonl").model_calls()]
        self.assertEqual(agents, ["merge_branch_s1", "merge_branch_s2", "merge_branch_s3", "merge_synthesizer"])

    def test_invalid_names_and_duplicate_destinations_are_rejected(self):
        create_session(self.root, "source", [("user", "hello")])
        with self.assertRaises(SessionBranchError):
            self.service.fork("source", destination_name="../escape")
        self.service.fork("source", destination_name="taken")
        with self.assertRaises(SessionBranchError):
            self.service.fork("source", destination_name="taken")


if __name__ == "__main__":
    unittest.main()
