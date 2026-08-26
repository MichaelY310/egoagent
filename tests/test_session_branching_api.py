import copy
import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from harness import Session

# The branch API itself has no YAML dependency.  The monolithic legacy server
# imports the optional Harbor adapter at module load time, so keep this focused
# integration test runnable in the repository's dependency-light test runtime.
try:
    import yaml  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda value: {}, safe_dump=lambda value, **_: "")

from harness_editor import server as server_module


class SessionBranchingApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "sessions"
        self.root.mkdir()
        self.previous_sessions_dir = server_module.SESSIONS_DIR
        server_module.SESSIONS_DIR = self.root
        source = Session(workspace=self.root.parent, save_dir=self.root / "source")
        message = {"role": "user", "content": "shared request"}
        source.record(message)
        source.record_full(copy.deepcopy(message))
        source.save()
        self.httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server_module.SESSIONS_DIR = self.previous_sessions_dir
        self.temporary.cleanup()

    def request(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def test_fork_direct_merge_and_lineage_routes(self):
        status, left = self.request("POST", "/api/session/source/fork", {"name": "left"})
        self.assertEqual(status, 200)
        self.assertEqual(left["operation"], "fork")
        self.request("POST", "/api/session/source/fork", {"name": "right"})

        right_session = Session(workspace=self.root.parent)
        right_session.load(self.root / "right")
        message = {"role": "assistant", "content": "right delta"}
        right_session.record(message)
        right_session.record_full(copy.deepcopy(message))
        right_session.save()

        _, merged = self.request("POST", "/api/sessions/merge", {
            "left": "left", "right": "right", "mode": "direct", "name": "merged",
        })
        self.assertEqual(merged["mode"], "direct")
        self.assertEqual(merged["right_new_messages"], 1)
        _, lineage = self.request("GET", "/api/session/merged/lineage")
        self.assertEqual(lineage["lineage"]["operation"], "merge")
        self.assertEqual([parent["name"] for parent in lineage["lineage"]["parents"]], ["left", "right"])

        _, sessions = self.request("GET", "/api/sessions")
        merged_info = next(item for item in sessions if item["name"] == "merged")
        self.assertEqual(merged_info["lineage"]["merge_mode"], "direct")
        self.assertEqual(merged_info["lineage"]["parents"], ["left", "right"])

    def test_api_rejects_traversal_destination(self):
        quoted = urllib.parse.quote("source", safe="")
        request = urllib.request.Request(
            self.base + f"/api/session/{quoted}/fork",
            data=json.dumps({"name": "../escape"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
