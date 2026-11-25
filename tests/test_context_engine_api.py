import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from egoagent_server import server as server_module


class ContextEngineHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        self.httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _post(self, path, body):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def test_index_plan_and_status_http_contract(self):
        status, indexed = self._post("/api/context/index", {"workspace": str(self.root)})
        self.assertEqual(status, 200)
        self.assertEqual(indexed["files"], 1)

        status, plan = self._post("/api/context/plan", {
            "workspace": str(self.root), "query": "answer", "token_budget": 300,
        })
        self.assertEqual(status, 200)
        self.assertTrue(plan["selected"])

        query = urllib.parse.urlencode({"workspace": str(self.root)})
        with urllib.request.urlopen(f"{self.base}/api/context/index/status?{query}", timeout=5) as response:
            detail = json.load(response)
        self.assertTrue(detail["available"])
