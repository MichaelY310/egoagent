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

try:
    import yaml  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda value: {}, safe_dump=lambda value, **_: "")

from harness_editor import server as server_module


class TrainingDataApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.sessions = self.temp_root / "sessions"
        self.sessions.mkdir()
        self.previous_sessions = server_module.SESSIONS_DIR
        self.previous_annotations = server_module.TRAINING_ANNOTATIONS_PATH
        server_module.SESSIONS_DIR = self.sessions
        server_module.TRAINING_ANNOTATIONS_PATH = self.temp_root / "training" / "annotations.json"

        session = Session(workspace=self.temp_root, save_dir=self.sessions / "demo")
        user = {"role": "user", "content": "Say hello"}
        assistant = {"role": "assistant", "content": "Hello"}
        session.record(user)
        session.record_full(dict(user))
        session.record(assistant)
        session.record_full(dict(assistant))
        call_id = session.begin_model_call(
            messages=[{"role": "system", "content": "Be concise"}, user],
            tools=[], agent="coder", model="tiny", provider="dummy", purpose="agent_step",
        )
        session.finish_model_call(call_id, agent="coder", content="Hello", finish_reason="stop")
        session.save()

        self.httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server_module.SESSIONS_DIR = self.previous_sessions
        server_module.TRAINING_ANNOTATIONS_PATH = self.previous_annotations
        self.temporary.cleanup()

    def request(self, method: str, path: str, body=None):
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def test_message_annotation_persists_and_exports_from_http_api(self):
        _, messages = self.request("GET", "/api/session/demo/messages")
        assistant = messages["messages"][1]
        target = assistant["_training"]
        status, saved = self.request("POST", "/api/training/annotations", {
            "session": "demo",
            "target_type": "message",
            "target_id": target["target_id"],
            "source_hash": target["source_hash"],
            "rating": "up",
            "important": True,
            "include_in_training": True,
            "tags": ["concise"],
            "note": "good greeting",
        })
        self.assertEqual(status, 200)
        self.assertEqual(saved["annotation"]["rating"], "up")
        _, listed = self.request("GET", "/api/training/annotations?session=demo")
        self.assertEqual(listed["summary"]["total"], 1)
        self.assertEqual(listed["annotations"][0]["target_id"], target["target_id"])

        destination = self.temp_root / "export"
        _, exported = self.request("POST", "/api/training/export", {
            "sessions": ["demo"],
            "destination": str(destination),
            "selection": "marked",
            "formats": ["message_sft", "unary_feedback"],
        })
        self.assertEqual(exported["manifest"]["counts"]["message_sft"], 1)
        self.assertTrue((destination / "message_sft_openai.jsonl").is_file())
        self.assertTrue((destination / "manifest.json").is_file())

    def test_stale_message_hash_returns_conflict(self):
        _, messages = self.request("GET", "/api/session/demo/messages")
        target = messages["messages"][1]["_training"]
        request = urllib.request.Request(
            self.base + "/api/training/annotations",
            data=json.dumps({
                "session": "demo",
                "target_type": "message",
                "target_id": target["target_id"],
                "source_hash": "stale",
                "rating": "up",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(raised.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
