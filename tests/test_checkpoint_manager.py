import tempfile
import unittest
from pathlib import Path

from harness_editor import checkpoint_manager
from harness_editor.change_tracker import clear_changes, configure_store, get_changes


class CheckpointManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.original_checkpoint_dir = checkpoint_manager.CHECKPOINT_DIR
        checkpoint_manager.configure(
            workspace=self.workspace,
            checkpoint_dir=self.root / "checkpoints",
        )
        configure_store(self.root / "change-journal.json")
        clear_changes()

    def tearDown(self):
        clear_changes()
        configure_store(None)
        checkpoint_manager.configure(checkpoint_dir=self.original_checkpoint_dir)
        self.temp_dir.cleanup()

    def test_checkpoint_content_and_timeline_survive_reload(self):
        target = self.workspace / "module.py"
        target.write_text("value = 1\n", encoding="utf-8")
        checkpoint = checkpoint_manager.create_checkpoint(
            "before refactor", [target], workspace=self.workspace
        )

        target.write_text("value = 2\n", encoding="utf-8")
        checkpoint_manager.reload_store()

        timeline = checkpoint_manager.list_checkpoints(workspace=self.workspace)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["id"], checkpoint["id"])
        self.assertEqual(timeline[0]["changed_count"], 1)
        self.assertEqual(timeline[0]["changed_files"][0]["action"], "restore")
        detail = checkpoint_manager.get_checkpoint(checkpoint["id"])
        self.assertEqual(detail["files"][0]["relative_path"], "module.py")

    def test_selective_restore_detects_post_preview_manual_edit(self):
        first = self.workspace / "first.txt"
        second = self.workspace / "second.txt"
        first.write_text("one\n", encoding="utf-8")
        second.write_text("two\n", encoding="utf-8")
        checkpoint = checkpoint_manager.create_checkpoint(
            "pair", [first, second], workspace=self.workspace
        )
        first.write_text("agent one\n", encoding="utf-8")
        second.write_text("agent two\n", encoding="utf-8")
        preview = checkpoint_manager.preview_restore(checkpoint["id"])

        first.write_text("manual one\n", encoding="utf-8")
        result = checkpoint_manager.rollback(
            checkpoint["id"],
            expected_revisions=preview["expected_revisions"],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(first.read_text(encoding="utf-8"), "manual one\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "two\n")
        self.assertEqual(result["restored_files"], 1)
        self.assertEqual(len(get_changes()), 1)

    def test_restore_deletion_requires_confirmation_and_is_reviewable(self):
        created_later = self.workspace / "generated.txt"
        checkpoint = checkpoint_manager.create_checkpoint(
            "before create", [created_later], workspace=self.workspace
        )
        created_later.write_text("generated\n", encoding="utf-8")
        preview = checkpoint_manager.preview_restore(checkpoint["id"])
        self.assertEqual(preview["impacts"][0]["action"], "delete")

        pending = checkpoint_manager.rollback(
            checkpoint["id"], expected_revisions=preview["expected_revisions"]
        )
        self.assertTrue(pending["delete_confirmation_required"])
        self.assertTrue(created_later.exists())

        restored = checkpoint_manager.rollback(
            checkpoint["id"],
            expected_revisions=preview["expected_revisions"],
            confirm_delete=True,
        )
        self.assertTrue(restored["ok"])
        self.assertFalse(created_later.exists())
        self.assertTrue(get_changes()[0]["is_deleted_file"])

    def test_harness_identity_environment_are_classified(self):
        paths = [
            self.workspace / "harness" / "demo" / "config.json",
            self.workspace / "identity" / "demo" / "id.json",
            self.workspace / "environment" / "demo" / "tool.py",
        ]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        checkpoint = checkpoint_manager.create_checkpoint(
            "agent mutation", paths, workspace=self.workspace
        )

        self.assertEqual(checkpoint["mutation_counts"]["harness"], 1)
        self.assertEqual(checkpoint["mutation_counts"]["identity"], 1)
        self.assertEqual(checkpoint["mutation_counts"]["environment"], 1)


if __name__ == "__main__":
    unittest.main()
