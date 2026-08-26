import tempfile
import unittest
from pathlib import Path

from harness_editor.background_workspace import (
    apply_handoff,
    create_isolated_workspace,
    preview_handoff,
)
from harness_editor.change_tracker import clear_changes, configure_store, get_changes


class BackgroundWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "keep.txt").write_text("old\n", encoding="utf-8")
        (self.root / "delete.txt").write_text("delete me\n", encoding="utf-8")
        (self.root / "conflict.txt").write_text("base\n", encoding="utf-8")
        configure_store(self.root / ".egoagent" / "review.json")
        clear_changes()

    def tearDown(self):
        clear_changes()
        configure_store(None)
        self.temp.cleanup()

    def test_isolated_changes_preview_conflict_and_reviewable_apply(self):
        isolation = create_isolated_workspace(self.root, "run-test")
        isolated = Path(isolation["workspace"])
        (isolated / "keep.txt").write_text("new\n", encoding="utf-8")
        (isolated / "created.txt").write_text("created\n", encoding="utf-8")
        (isolated / "delete.txt").unlink()
        (isolated / "binary.bin").write_bytes(b"\x00\x01\x02")
        (self.root / "conflict.txt").write_text("manual\n", encoding="utf-8")
        (isolated / "conflict.txt").write_text("agent\n", encoding="utf-8")

        preview = preview_handoff(self.root, isolated, "run-test")
        by_path = {item["path"]: item for item in preview["changes"]}
        self.assertEqual(by_path["keep.txt"]["kind"], "modified")
        self.assertEqual(by_path["created.txt"]["kind"], "created")
        self.assertEqual(by_path["delete.txt"]["kind"], "deleted")
        self.assertTrue(by_path["binary.bin"]["binary"])
        self.assertTrue(by_path["conflict.txt"]["conflict"])

        confirmation = apply_handoff(
            self.root, isolated, "run-test", ["delete.txt"], preview["expected_revisions"]
        )
        self.assertTrue(confirmation["delete_confirmation_required"])
        self.assertTrue((self.root / "delete.txt").exists())

        result = apply_handoff(
            self.root,
            isolated,
            "run-test",
            ["keep.txt", "created.txt", "delete.txt", "binary.bin", "conflict.txt"],
            preview["expected_revisions"],
            confirm_delete=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(set(result["applied"]), {"keep.txt", "created.txt", "delete.txt", "binary.bin"})
        self.assertEqual([item["path"] for item in result["conflicts"]], ["conflict.txt"])
        self.assertEqual((self.root / "keep.txt").read_text(encoding="utf-8"), "new\n")
        self.assertFalse((self.root / "delete.txt").exists())
        self.assertEqual((self.root / "binary.bin").read_bytes(), b"\x00\x01\x02")
        self.assertEqual((self.root / "conflict.txt").read_text(encoding="utf-8"), "manual\n")

        changes = get_changes(transaction_id="background-handoff:run-test")
        self.assertEqual(len(changes), 4)
        self.assertTrue(all(change["status"] == "pending" for change in changes))


if __name__ == "__main__":
    unittest.main()
