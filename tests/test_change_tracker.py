import tempfile
import unittest
from pathlib import Path

from harness_editor.change_tracker import (
    accept_change,
    apply_text_change,
    clear_changes,
    configure_store,
    get_change_content,
    get_changes,
    get_last_operation_error,
    record_change,
    record_binary_change,
    record_move,
    reload_store,
    reject_change,
    undo_change,
)


class ChangeTrackerReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        configure_store(self.root / "review-journal.json")
        clear_changes()

    def tearDown(self):
        clear_changes()
        self.temp_dir.cleanup()

    def test_agent_edit_is_live_then_reject_and_undo_only_the_decision(self):
        target = self.root / "sample.py"
        old = "def value():\n    return 1\n"
        new = "def value():\n    return 2\n\ndef added():\n    return 3\n"
        target.write_text(new, encoding="utf-8")
        index = record_change(target, old, new, "patch_file")

        change = get_changes()[0]
        self.assertEqual(change["status"], "pending")
        self.assertEqual(target.read_text(encoding="utf-8"), new)

        self.assertTrue(reject_change(index, "manual review", hunk_id=0))
        self.assertNotEqual(target.read_text(encoding="utf-8"), new)
        self.assertTrue(get_changes()[0]["hunks"][0]["can_undo"])

        self.assertTrue(undo_change(index, hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), new)
        self.assertEqual(get_changes()[0]["hunks"][0]["status"], "pending")

    def test_local_patch_normalizes_platform_newlines_and_keeps_two_hunks(self):
        target = self.root / "two_edits.py"
        old = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
        platform_written = old.replace("return 1", "return 10").replace("return 2", "return 20").replace("\n", "\r\n")
        target.write_bytes(platform_written.encode("utf-8"))

        record_change(target, old, platform_written, "multi_edit")
        change = get_changes()[0]

        self.assertEqual(len(change["hunks"]), 2)
        self.assertNotIn(b"\r\n", target.read_bytes())
        self.assertEqual("".join(change["hunks"][0]["old_lines"]), "    return 1\n")
        self.assertEqual("".join(change["hunks"][1]["new_lines"]), "    return 20\n")

    def test_accept_keeps_agent_content_and_undo_restores_pending_review(self):
        target = self.root / "accepted.py"
        old = "answer = 1\n"
        new = "answer = 42\n"
        target.write_text(new, encoding="utf-8")
        index = record_change(target, old, new, "write_file")

        self.assertTrue(accept_change(index, hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), new)
        self.assertEqual(get_changes()[0]["hunks"][0]["status"], "accepted")

        self.assertTrue(undo_change(index, hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), new)
        self.assertEqual(get_changes()[0]["hunks"][0]["status"], "pending")

    def test_apply_text_change_is_atomic_and_revision_checked(self):
        target = self.root / "inline.py"
        target.write_text("value = 1\n", encoding="utf-8")

        index = apply_text_change(target, "value = 1\n", "value = 2\n", "inline-edit")
        self.assertIsNotNone(index)
        self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")
        self.assertEqual(get_changes()[0]["index"], index)

        self.assertIsNone(
            apply_text_change(target, "value = 1\n", "value = 3\n", "stale-inline-edit")
        )
        self.assertEqual(get_last_operation_error()["code"], "revision_conflict")
        self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")

    def test_new_file_is_marked_then_delete_can_be_undone(self):
        target = self.root / "created.py"
        content = "print('created by agent')\n"
        target.write_text(content, encoding="utf-8")
        index = record_change(target, None, content, "write_file")

        change = get_changes()[0]
        self.assertTrue(change["is_new_file"])
        self.assertTrue(change["file_exists"])
        self.assertFalse(reject_change(index, "not confirmed", hunk_id=0))
        self.assertEqual(get_last_operation_error()["code"], "delete_confirmation_required")
        self.assertTrue(target.exists())
        self.assertTrue(reject_change(index, "delete confirmed", hunk_id=0, confirm_delete=True))
        self.assertFalse(target.exists())

        self.assertTrue(undo_change(index, hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), content)

    def test_manual_edit_blocks_destructive_reject(self):
        target = self.root / "conflict.py"
        old = "name = 'old'\n"
        new = "name = 'agent'\n"
        target.write_text(new, encoding="utf-8")
        index = record_change(target, old, new, "patch_file")
        target.write_text("name = 'user'\n", encoding="utf-8")

        self.assertFalse(reject_change(index, "should conflict", hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), "name = 'user'\n")
        self.assertEqual(get_changes()[0]["hunks"][0]["status"], "pending")
        self.assertEqual(get_changes()[0]["status"], "conflict")
        self.assertEqual(get_last_operation_error()["code"], "revision_conflict")

    def test_review_journal_and_decision_history_survive_restart(self):
        target = self.root / "durable.py"
        old = "value = 1\n"
        new = "value = 2\n"
        target.write_text(new, encoding="utf-8")
        index = record_change(target, old, new, "patch_file", transaction_id="run-1")
        change_before = get_changes()[0]
        stable_hunk_id = change_before["hunks"][0]["id"]
        self.assertTrue(accept_change(index, stable_hunk_id))

        self.assertEqual(reload_store(), 1)
        change_after = get_changes()[0]
        self.assertEqual(change_after["id"], change_before["id"])
        self.assertEqual(change_after["hunks"][0]["id"], stable_hunk_id)
        self.assertEqual(change_after["hunks"][0]["status"], "accepted")
        self.assertTrue(change_after["hunks"][0]["can_undo"])
        self.assertTrue(undo_change(change_after["id"], stable_hunk_id))
        self.assertEqual(target.read_text(encoding="utf-8"), new)

    def test_consecutive_edits_in_one_transaction_compose_base_to_final(self):
        target = self.root / "composed.py"
        base = "a = 1\n"
        middle = "a = 2\n"
        final = "a = 3\nb = 4\n"
        target.write_text(middle, encoding="utf-8")
        first = record_change(target, base, middle, "patch_file", transaction_id="run-compose")
        target.write_text(final, encoding="utf-8")
        second = record_change(target, middle, final, "patch_file", transaction_id="run-compose")

        self.assertEqual(first, second)
        self.assertEqual(len(get_changes()), 1)
        change = get_changes()[0]
        self.assertEqual(change["status"], "pending")
        self.assertIn("sha256:", change["base_revision"])
        self.assertTrue(reject_change(change["id"], "restore complete base"))
        self.assertEqual(target.read_text(encoding="utf-8"), base)

    def test_native_diff_detail_keeps_exact_historical_before_and_after(self):
        target = self.root / "history.py"
        base = "value = 1\n"
        first_result = "value = 2\n"
        later_result = "value = 3\n"
        target.write_text(first_result, encoding="utf-8")
        first = record_change(target, base, first_result, "patch_file", transaction_id="run-first")
        target.write_text(later_result, encoding="utf-8")
        record_change(target, first_result, later_result, "patch_file", transaction_id="run-later")

        detail = get_change_content(first)
        self.assertEqual(detail["transaction_id"], "run-first")
        self.assertEqual(detail["old_content"], base)
        self.assertEqual(detail["new_content"], first_result)
        self.assertNotEqual(detail["new_content"], target.read_text(encoding="utf-8"))

    def test_deleted_file_can_be_rejected_and_restored(self):
        target = self.root / "deleted.txt"
        old = "keep me\n"
        index = record_change(target, old, None, "delete_file")
        self.assertFalse(target.exists())
        change = get_changes()[0]
        self.assertTrue(change["is_deleted_file"])
        self.assertTrue(reject_change(index, "restore deletion", hunk_id=0))
        self.assertEqual(target.read_text(encoding="utf-8"), old)

    def test_empty_new_file_is_reviewable(self):
        target = self.root / "empty.txt"
        target.write_text("", encoding="utf-8")
        index = record_change(target, None, "", "write_file")
        change = get_changes()[0]
        self.assertEqual(len(change["hunks"]), 1)
        self.assertEqual(change["hunks"][0]["tag"], "file_state")
        self.assertFalse(reject_change(index, hunk_id=0))
        self.assertTrue(reject_change(index, hunk_id=0, confirm_delete=True))
        self.assertFalse(target.exists())

    def test_binary_replace_reject_undo_and_restart(self):
        target = self.root / "image.bin"
        old = b"\x00\x01old\xff"
        new = b"\x00\x02new\xfe"
        target.write_bytes(new)
        index = record_binary_change(target, old, new, "write_binary")
        change = get_changes()[0]
        self.assertEqual(change["change_type"], "binary")
        self.assertEqual(change["old_size"], len(old))
        self.assertEqual(change["new_size"], len(new))
        self.assertTrue(reject_change(index, "binary review", hunk_id=0))
        self.assertEqual(target.read_bytes(), old)
        reload_store()
        change = get_changes()[0]
        self.assertTrue(undo_change(change["id"], change["hunks"][0]["id"]))
        self.assertEqual(target.read_bytes(), new)

    def test_move_reject_and_undo_moves_only_the_reviewed_file(self):
        source = self.root / "before.txt"
        target = self.root / "nested" / "after.txt"
        target.parent.mkdir()
        target.write_text("moved\n", encoding="utf-8")
        index = record_move(source, target, transaction_id="move-run")
        change = get_changes()[0]
        self.assertEqual(change["change_type"], "move")
        self.assertEqual(change["source_path"], str(source.resolve()))
        self.assertTrue(reject_change(index, "restore original name", hunk_id=0))
        self.assertTrue(source.is_file())
        self.assertFalse(target.exists())
        self.assertTrue(undo_change(change["id"], change["hunks"][0]["id"]))
        self.assertFalse(source.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "moved\n")

    def test_move_conflict_does_not_overwrite_a_new_destination(self):
        source = self.root / "old-name.txt"
        target = self.root / "new-name.txt"
        target.write_text("agent moved\n", encoding="utf-8")
        index = record_move(source, target)
        source.write_text("user file\n", encoding="utf-8")
        self.assertFalse(reject_change(index, "would collide", hunk_id=0))
        self.assertEqual(source.read_text(encoding="utf-8"), "user file\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "agent moved\n")
        self.assertEqual(get_last_operation_error()["code"], "revision_conflict")


if __name__ == "__main__":
    unittest.main()
