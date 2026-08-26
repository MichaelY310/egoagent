import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from harness_editor import server as server_module


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.httpd = server_module.ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.APIHandler
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def test_workspace_query_uses_the_ide_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            url = self.base + "/api/workspace?" + urllib.parse.urlencode(
                {"workspace": directory}
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read())

            self.assertEqual(response.status, 200)
            self.assertEqual(Path(data["workspace"]), Path(directory).resolve())
            self.assertEqual(data["name"], Path(directory).name)

    def test_workspace_query_rejects_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "does-not-exist")
            url = self.base + "/api/workspace?" + urllib.parse.urlencode(
                {"workspace": missing}
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(url, timeout=5)

            self.assertEqual(raised.exception.code, 404)
            body = json.loads(raised.exception.read())
            self.assertIn("does not exist", body["error"])


if __name__ == "__main__":
    unittest.main()
