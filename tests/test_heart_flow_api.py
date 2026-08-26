import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from heart_flow import api
from heart_flow.service import FlowRelayService


class Handler:
    def __init__(self, body=None):
        self.body = body or {}
        self.response = None
        self.error = None

    def _read_body(self):
        return self.body

    def _send_json(self, value):
        self.response = value

    def _send_error(self, value, status):
        self.error = (status, value)


class Portfolio:
    def __init__(self, project, session):
        self.project = project
        self.session = session

    def list_projects(self, **_kwargs):
        return [self.project]

    def list_sessions(self, **_kwargs):
        return [self.session]


class Runs:
    def list(self):
        return []


class HeartFlowApiTests(unittest.TestCase):
    def test_status_focus_and_park_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir = root / "session"
            session_dir.mkdir()
            (session_dir / "messages.json").write_text(json.dumps([
                {"role": "user", "content": "implement demo.py"},
                {"role": "assistant", "content": "Next: run tests"},
            ]), encoding="utf-8")
            project = {"id": "p1", "title": "Demo", "workspace": str(root)}
            session = {"name": "s1", "path": str(session_dir), "message_count": 2, "timestamp": 1}
            portfolio = Portfolio(project, session)
            service = FlowRelayService(root / "state.json")

            handler = Handler({"project_id": "p1", "minutes": 40})
            self.assertTrue(api.handle_post(handler, "/api/heart-flow/focus", service=service, portfolio=portfolio, runs=Runs()))
            self.assertTrue(handler.response["ok"])

            handler = Handler({"project_id": "p1"})
            self.assertTrue(api.handle_post(handler, "/api/heart-flow/park", service=service, portfolio=portfolio, runs=Runs()))
            self.assertEqual(handler.response["capsule"]["session"], "s1")

            handler = Handler()
            parsed = SimpleNamespace(query="workspace=/demo")
            self.assertTrue(api.handle_get(handler, "/api/heart-flow/status", parsed, service=service, portfolio=portfolio, runs=Runs()))
            self.assertEqual(handler.response["focused_project"]["id"], "p1")
            self.assertEqual(handler.response["reentry_capsule"]["session"], "s1")


if __name__ == "__main__":
    unittest.main()
