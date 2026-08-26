import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from harness_editor import server as server_module
from harness_editor.change_tracker import clear_changes, configure_store, record_change


class ChangeReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        configure_store(self.root / "review-journal.json")
        clear_changes()
        self.httpd = server_module.ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.APIHandler
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        clear_changes()
        self.temp_dir.cleanup()

    def _get_json(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def _post_json(self, path, body):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def test_changes_endpoint_filters_by_workspace_and_keeps_stable_ids(self):
        workspace = self.root / "workspace"
        other = self.root / "other"
        workspace.mkdir()
        other.mkdir()

        included = workspace / "included.py"
        excluded = other / "excluded.py"
        included.write_text("value = 2\n", encoding="utf-8")
        excluded.write_text("value = 3\n", encoding="utf-8")
        included_index = record_change(included, "value = 1\n", "value = 2\n", "test")
        record_change(excluded, "value = 1\n", "value = 3\n", "test")

        all_changes = self._get_json("/api/session/changes")
        query = urllib.parse.urlencode({"workspace": str(workspace)})
        filtered = self._get_json(f"/api/session/changes?{query}")

        self.assertEqual(len(all_changes), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["index"], included_index)
        self.assertEqual(filtered[0]["file_path"], str(included))
        self.assertIsInstance(filtered[0]["id"], str)
        self.assertIsInstance(filtered[0]["hunks"][0]["id"], str)

    def test_changes_endpoint_returns_empty_for_unrelated_workspace(self):
        changed = self.root / "workspace" / "changed.py"
        changed.parent.mkdir()
        changed.write_text("answer = 42\n", encoding="utf-8")
        record_change(changed, "answer = 1\n", "answer = 42\n", "test")

        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        query = urllib.parse.urlencode({"workspace": str(unrelated)})

        self.assertEqual(self._get_json(f"/api/session/changes?{query}"), [])

    def test_workspace_view_hides_missing_file_even_when_parent_still_exists(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        stale = workspace / "stale.py"
        stale.write_text("answer = 2\n", encoding="utf-8")
        record_change(stale, "answer = 1\n", "answer = 2\n", "test")
        stale.unlink()
        deleted = workspace / "intentionally-deleted.py"
        record_change(deleted, "keep = True\n", None, "delete_file")

        query = urllib.parse.urlencode({"workspace": str(workspace)})
        audit_query = urllib.parse.urlencode({"workspace": str(workspace), "include_stale": "1"})

        visible = self._get_json(f"/api/session/changes?{query}")
        self.assertEqual([item["file_path"] for item in visible], [str(deleted)])
        self.assertTrue(visible[0]["is_deleted_file"])
        self.assertEqual(len(self._get_json(f"/api/session/changes?{audit_query}")), 2)

    def test_change_content_endpoint_returns_exact_lazy_diff_payload(self):
        target = self.root / "exact.py"
        old = "first\nsecond\n"
        new = "first\nchanged\n"
        target.write_text(new, encoding="utf-8")
        selector = record_change(target, old, new, "patch_file", transaction_id="run-exact")

        query = urllib.parse.urlencode({"id": selector})
        detail = self._get_json(f"/api/session/changes/content?{query}")
        self.assertEqual(detail["transaction_id"], "run-exact")
        self.assertEqual(detail["old_content"], old)
        self.assertEqual(detail["new_content"], new)

    def test_clear_workspace_endpoint_keeps_unrelated_review_records(self):
        workspace = self.root / "workspace"
        other = self.root / "other"
        workspace.mkdir()
        other.mkdir()
        target = workspace / "demo.py"
        unrelated = other / "keep.py"
        target.write_text("value = 2\n", encoding="utf-8")
        unrelated.write_text("value = 3\n", encoding="utf-8")
        record_change(target, "value = 1\n", "value = 2\n", "test")
        record_change(unrelated, "value = 1\n", "value = 3\n", "test")

        status, result = self._post_json(
            "/api/session/changes/clear-workspace",
            {"workspace": str(workspace)},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["removed"], 1)
        self.assertEqual([change["file_path"] for change in self._get_json("/api/session/changes")], [str(unrelated)])

    def test_workspace_view_hides_stale_and_internal_child_run_entries(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        live = workspace / "src" / "live.py"
        live.parent.mkdir()
        live.write_text("answer = 2\n", encoding="utf-8")
        record_change(live, "answer = 1\n", "answer = 2\n", "test")

        stale = workspace / "tmp" / "removed" / "stale.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale = 2\n", encoding="utf-8")
        record_change(stale, "stale = 1\n", "stale = 2\n", "test")
        stale.unlink()
        stale.parent.rmdir()

        internal = workspace / ".egoagent" / "task_runs" / "run-1" / "agent.py"
        internal.parent.mkdir(parents=True)
        internal.write_text("value = 2\n", encoding="utf-8")
        record_change(internal, "value = 1\n", "value = 2\n", "test")

        query = urllib.parse.urlencode({"workspace": str(workspace)})
        visible = self._get_json(f"/api/session/changes?{query}")
        self.assertEqual([item["file_path"] for item in visible], [str(live)])

        audit_query = urllib.parse.urlencode({
            "workspace": str(workspace),
            "include_stale": "1",
            "include_internal": "1",
        })
        self.assertEqual(len(self._get_json(f"/api/session/changes?{audit_query}")), 3)

    def test_apply_text_endpoint_records_edit_and_rejects_stale_or_escaped_target(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        target = workspace / "sample.py"
        target.write_text("answer = 1\n", encoding="utf-8")
        payload = {
            "workspace": str(workspace),
            "file": str(target),
            "old_text": "answer = 1\n",
            "new_text": "answer = 42\n",
            "transaction_id": "inline-e2e",
            "tool_name": "void-inline-edit",
        }

        status, result = self._post_json("/api/session/changes/apply-text", payload)
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "answer = 42\n")
        self.assertEqual(result["change"]["transaction_id"], "inline-e2e")

        with self.assertRaises(urllib.error.HTTPError) as stale:
            self._post_json("/api/session/changes/apply-text", payload)
        self.assertEqual(stale.exception.code, 409)
        self.assertEqual(target.read_text(encoding="utf-8"), "answer = 42\n")

        escaped = dict(payload, file=str(self.root / "outside.py"), old_text=None, new_text="x\n")
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self._post_json("/api/session/changes/apply-text", escaped)
        self.assertEqual(denied.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
