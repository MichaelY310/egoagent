import json
import tempfile
import unittest
from pathlib import Path

from harness import Session
from training_data import (
    TrainingAnnotationStore,
    annotated_session_messages,
    export_annotated_training_data,
    message_target_id,
    resolve_target_source,
)


def _make_session(root: Path, name: str, answer: str) -> tuple[Path, str]:
    location = root / name
    session = Session(workspace=root, save_dir=location)
    user = {"role": "user", "content": "Write a tiny hello function."}
    assistant = {"role": "assistant", "name": "coder", "content": answer}
    session.record(user)
    session.record_full(dict(user))
    session.record(assistant)
    session.record_full(dict(assistant))
    call_id = session.begin_model_call(
        messages=[{"role": "system", "content": "You are a coder."}, user],
        tools=[{"type": "function", "function": {"name": "write_file"}}],
        agent="coder",
        model="tiny",
        provider="dummy",
        purpose="agent_step",
    )
    session.finish_model_call(call_id, agent="coder", content=answer, finish_reason="stop")
    session.save()
    return location, call_id


class TrainingAnnotationTests(unittest.TestCase):
    def test_annotations_are_mutable_sidecars_with_stable_content_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir, _ = _make_session(root, "liked", "def hello(): return 'hi'")
            store = TrainingAnnotationStore(root / "annotations.json")
            messages = annotated_session_messages(session_dir)
            target = messages[1]["_training"]
            _, verified_hash = resolve_target_source("liked", session_dir, "message", target["target_id"])
            self.assertEqual(verified_hash, target["source_hash"])

            first = store.upsert(
                session="liked",
                target_type="message",
                target_id=target["target_id"],
                source_hash=verified_hash,
                rating="up",
                important=True,
                include_in_training=True,
                tags=["code", "demo", "code"],
                note="clean answer",
            )
            second = store.upsert(
                session="liked",
                target_type="message",
                target_id=target["target_id"],
                source_hash=verified_hash,
                rating="neutral",
                tags=["reviewed"],
            )
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(store.summary()["total"], 1)
            self.assertEqual(store.list(session="liked")[0]["tags"], ["reviewed"])
            self.assertTrue((session_dir / "trajectory.jsonl").is_file())
            self.assertNotIn("training-annotation", (session_dir / "trajectory.jsonl").read_text(encoding="utf-8"))

    def test_export_separates_positive_sft_unpaired_and_paired_feedback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            liked_dir, liked_call = _make_session(root, "liked", "def hello():\n    return 'hello'")
            disliked_dir, disliked_call = _make_session(root, "disliked", "hello = 1 / 0")
            store = TrainingAnnotationStore(root / "annotations.json")
            for session_name, session_dir, call_id, rating in (
                ("liked", liked_dir, liked_call, "up"),
                ("disliked", disliked_dir, disliked_call, "down"),
            ):
                _, source_hash = resolve_target_source(session_name, session_dir, "model_call", call_id)
                store.upsert(
                    session=session_name,
                    target_type="model_call",
                    target_id=call_id,
                    source_hash=source_hash,
                    rating=rating,
                    important=rating == "up",
                    include_in_training=True,
                    tags=["hello"],
                )

            manifest = export_annotated_training_data(
                [("liked", liked_dir), ("disliked", disliked_dir)],
                root / "export",
                store=store,
                selection="marked",
            )
            self.assertEqual(manifest["counts"]["model_call_sft"], 1)
            self.assertEqual(manifest["counts"]["kto"], 2)
            self.assertEqual(manifest["counts"]["preference"], 1)
            self.assertGreater(manifest["counts"]["trajectory"], 0)
            positive = json.loads((root / "export" / "model_calls.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(positive["response"]["content"], "def hello():\n    return 'hello'")
            preference = json.loads((root / "export" / "preferences_trl.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(preference["chosen"][0]["content"], "def hello():\n    return 'hello'")
            self.assertEqual(preference["rejected"][0]["content"], "hello = 1 / 0")
            kto = [json.loads(line) for line in (root / "export" / "kto_trl.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["label"] for row in kto}, {True, False})

    def test_whole_session_annotation_exports_a_conversation_but_downvote_is_not_sft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            liked_dir, _ = _make_session(root, "whole", "useful response")
            store = TrainingAnnotationStore(root / "annotations.json")
            _, source_hash = resolve_target_source("whole", liked_dir, "session", "whole")
            store.upsert(
                session="whole",
                target_type="session",
                target_id="whole",
                source_hash=source_hash,
                rating="up",
                include_in_training=True,
            )
            manifest = export_annotated_training_data(
                [("whole", liked_dir)], root / "positive", store=store, selection="marked"
            )
            self.assertEqual(manifest["counts"]["conversation"], 1)
            row = json.loads((root / "positive" / "conversations_openai.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(list(row), ["messages"])

            store.upsert(
                session="whole",
                target_type="session",
                target_id="whole",
                source_hash=source_hash,
                rating="down",
                include_in_training=True,
            )
            manifest = export_annotated_training_data(
                [("whole", liked_dir)], root / "negative", store=store, selection="marked"
            )
            self.assertEqual(manifest["counts"]["conversation"], 0)
            self.assertEqual(manifest["counts"]["model_call_sft"], 0)
            self.assertGreater(manifest["counts"]["unary_feedback"], 0)

    def test_export_rejects_filesystem_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir, _ = _make_session(root, "s", "ok")
            with self.assertRaisesRegex(ValueError, "filesystem root"):
                export_annotated_training_data(
                    [("s", session_dir)], Path(session_dir.anchor), store=TrainingAnnotationStore(root / "a.json"), selection="all"
                )


if __name__ == "__main__":
    unittest.main()
