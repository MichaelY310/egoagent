import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Agent
from harness import Harness
from harness_editor import agent_creator


ROOT = Path(__file__).resolve().parents[1]


class AgentCreatorTests(unittest.TestCase):
    def test_plain_language_creation_produces_loadable_identity_and_visual_harness(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identities = project / "identity"
            harnesses = project / "harness"
            identities.mkdir()
            harnesses.mkdir()
            dante = identities / "dante"
            (dante / "ego" / "skills").mkdir(parents=True)
            (dante / "ego" / "knowledge").mkdir(parents=True)
            (dante / "superego").mkdir()
            (dante / "id.json").write_text((ROOT / "identity" / "dante" / "id.json").read_text(encoding="utf-8"), encoding="utf-8")
            for skill in ("read", "write", "patch", "search", "end_session"):
                shutil.copytree(ROOT / "identity" / "dante" / "ego" / "skills" / skill, dante / "ego" / "skills" / skill)

            with patch.object(agent_creator, "PROJECT_ROOT", project), patch.object(agent_creator, "IDENTITY_DIR", identities):
                result = agent_creator.create_agent_from_description(
                    "Create a Python code review agent that checks patches and explains risks.",
                    "review_bot",
                )

            identity_path = identities / "review_bot"
            harness_path = harnesses / "review_bot_harness"
            self.assertTrue((identity_path / "id.json").is_file())
            self.assertTrue((identity_path / "superego" / "config.json").is_file())
            self.assertTrue((identity_path / "ego" / "skills" / "read" / "meta.json").is_file())
            self.assertTrue((identity_path / "ego" / "knowledge" / "python" / "meta.json").is_file())
            self.assertTrue((harness_path / "config.json").is_file())
            self.assertEqual(result["recommended_harness"], "review_bot_harness")

            agent = Agent(identity_path, name="agent", workspace=project)
            harness = Harness(harness_path, agents={"agent": agent}, workspace=project)
            self.assertEqual(harness.config["pipeline"]["start"], "input")
            self.assertIn("think", harness.config["pipeline"]["nodes"])
            tool_names = {agent._short_name(name) for name in agent.tools}
            self.assertIn("read_file", tool_names)
            knowledge_names = {agent._short_name(name) for name in agent.knowledges}
            self.assertIn("python", knowledge_names)

    def test_structured_spec_controls_identity_without_keyword_template_selection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identities = project / "identity"
            harnesses = project / "harness"
            identities.mkdir()
            harnesses.mkdir()
            dante = identities / "dante"
            (dante / "ego" / "skills").mkdir(parents=True)
            (dante / "ego" / "knowledge").mkdir(parents=True)
            (dante / "superego").mkdir()
            (dante / "id.json").write_text((ROOT / "identity" / "dante" / "id.json").read_text(encoding="utf-8"), encoding="utf-8")
            shutil.copytree(ROOT / "identity" / "dante" / "ego" / "skills" / "read", dante / "ego" / "skills" / "read")

            spec = {
                "name": "evidence_librarian",
                "description": "Maintain a traceable local evidence collection.",
                "role": "evidence librarian",
                "traits": ["skeptical", "organized"],
                "tone": "compact and cited",
                "language": "en",
                "temperature": 0.15,
                "system_prompt": "Index local evidence and cite exact paths. Never use unsupported claims.",
                "skills": ["read"],
                "knowledge_topics": ["evidence_policy"],
                "allow_self_evolution": False,
            }
            with patch.object(agent_creator, "PROJECT_ROOT", project), patch.object(agent_creator, "IDENTITY_DIR", identities):
                result = agent_creator.create_agent_from_spec(spec)

            identity_config = json.loads((identities / "evidence_librarian" / "id.json").read_text(encoding="utf-8"))
            superego = json.loads((identities / "evidence_librarian" / "superego" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(identity_config["role"], "evidence librarian")
            self.assertEqual(identity_config["personality"]["traits"], ["skeptical", "organized"])
            self.assertEqual(result["skills"], ["read"])
            self.assertFalse(superego["allow_modify_identity"])
            self.assertTrue((harnesses / "evidence_librarian_harness" / "config.json").is_file())


if __name__ == "__main__":
    unittest.main()
