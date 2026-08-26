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

try:
    import yaml  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda value: {}, safe_dump=lambda value, **_: "")

from harness_editor import server as server_module
from project_portfolio import project_id_for_workspace


class ProjectPortfolioApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.alpha = self.root / "alpha"
        self.beta = self.root / "beta"
        self.alpha.mkdir()
        self.beta.mkdir()
        self.previous_sessions = server_module.SESSIONS_DIR
        self.previous_portfolio = server_module.PROJECT_PORTFOLIO_PATH
        server_module.SESSIONS_DIR = self.sessions
        server_module.PROJECT_PORTFOLIO_PATH = self.root / "state" / "portfolio.json"
        self._save("alpha_run", self.alpha, "alpha request")
        self._save("beta_run", self.beta, "beta request")
        self.httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server_module.SESSIONS_DIR = self.previous_sessions
        server_module.PROJECT_PORTFOLIO_PATH = self.previous_portfolio
        self.temporary.cleanup()

    def _save(self, name, workspace, content):
        session = Session(workspace=workspace, save_dir=self.sessions / name)
        message = {"role": "user", "content": content}
        session.record(message)
        session.record_full(copy.deepcopy(message))
        session.save()

    def request(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def test_project_grouping_pin_and_cross_project_merge_guard(self):
        query = urllib.parse.urlencode({"workspace": str(self.alpha)})
        _, result = self.request("GET", "/api/projects?" + query)
        self.assertEqual(len(result["projects"]), 2)
        alpha_id = project_id_for_workspace(self.alpha)
        alpha = next(project for project in result["projects"] if project["id"] == alpha_id)
        self.assertTrue(alpha["current"])
        self.assertEqual(alpha["session_count"], 1)

        _, sessions = self.request("GET", "/api/projects/sessions?" + urllib.parse.urlencode({"project_id": alpha_id}))
        self.assertEqual([session["name"] for session in sessions["sessions"]], ["alpha_run"])
        _, updated = self.request("POST", "/api/projects/session/update", {
            "session": "alpha_run", "changes": {"pinned": True},
        })
        self.assertTrue(updated["session"]["pinned"])

        request = urllib.request.Request(
            self.base + "/api/sessions/merge",
            data=json.dumps({"left": "alpha_run", "right": "beta_run", "mode": "direct"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
