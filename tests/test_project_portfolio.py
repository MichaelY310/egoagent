import copy
import json
import tempfile
import unittest
from pathlib import Path

from harness import Session
from project_portfolio import ProjectPortfolio, infer_session_workspace, project_id_for_workspace
from session_branching import SessionBranchError, SessionBranchService


def save_session(root: Path, name: str, workspace: Path, content: str) -> Path:
    session = Session(workspace=workspace, save_dir=root / name)
    message = {"role": "user", "content": content}
    session.record(message)
    session.record_full(copy.deepcopy(message))
    session.save()
    return root / name


class ProjectPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.alpha = self.root / "alpha"
        self.beta = self.root / "beta"
        self.alpha.mkdir()
        self.beta.mkdir()
        self.portfolio = ProjectPortfolio(self.root / "state" / "portfolio.json", self.sessions)

    def tearDown(self):
        self.temporary.cleanup()

    def test_session_metadata_records_workspace_and_projects_are_grouped(self):
        alpha_session = save_session(self.sessions, "alpha_run", self.alpha, "implement alpha")
        save_session(self.sessions, "beta_run", self.beta, "debug beta")
        metadata = json.loads((alpha_session / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(metadata["workspace"]), self.alpha.resolve())
        self.assertEqual(infer_session_workspace(alpha_session)[0], str(self.alpha.resolve()))

        self.portfolio.register_project(self.alpha, title="Alpha product")
        projects = self.portfolio.list_projects(current_workspace=self.beta)
        self.assertEqual({project["id"] for project in projects}, {
            project_id_for_workspace(self.alpha),
            project_id_for_workspace(self.beta),
        })
        alpha = next(project for project in projects if project["workspace"] == str(self.alpha.resolve()))
        self.assertEqual(alpha["title"], "Alpha product")
        self.assertEqual(alpha["session_count"], 1)
        self.assertFalse(alpha["current"])
        beta = next(project for project in projects if project["workspace"] == str(self.beta.resolve()))
        self.assertTrue(beta["current"])

    def test_pin_and_active_session_metadata_do_not_modify_source_session(self):
        session_dir = save_session(self.sessions, "alpha_run", self.alpha, "keep immutable")
        before = (session_dir / "messages.json").read_bytes()
        self.portfolio.register_project(self.alpha)
        saved = self.portfolio.update_session("alpha_run", {"pinned": True})
        self.assertTrue(saved["pinned"])
        listed = self.portfolio.list_sessions(workspace=self.alpha)
        self.assertTrue(listed[0]["pinned"])
        project = self.portfolio.list_projects(current_workspace=self.alpha)[0]
        self.assertEqual(project["active_session"], "alpha_run")
        self.assertEqual((session_dir / "messages.json").read_bytes(), before)

    def test_direct_cross_project_merge_is_rejected(self):
        save_session(self.sessions, "alpha_run", self.alpha, "alpha paths")
        save_session(self.sessions, "beta_run", self.beta, "beta paths")
        service = SessionBranchService(self.sessions, workspace=self.alpha)
        with self.assertRaisesRegex(SessionBranchError, "disabled across projects"):
            service.merge("alpha_run", "beta_run", mode="direct")


if __name__ == "__main__":
    unittest.main()
