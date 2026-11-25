import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from harness_editor.server import _build_chat_harness


@patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-not-a-real-key"})
class ChatWorkspaceTests(unittest.TestCase):
    def test_default_chat_stack_is_the_flagship_code_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            harness, slots = _build_chat_harness([], workspace=directory)

            self.assertEqual(harness.config["name"], "code_agent_fast")
            self.assertEqual(set(slots), {"agent", "governor"})
            self.assertTrue(
                all(agent.identity.ID["name"] == "adaptive_deepseek_coder" for agent in harness.agents.values())
            )

    def test_openai_compatible_chat_builds_agent_in_requested_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            harness, _slots = _build_chat_harness(
                [{"role": "user", "content": "Inspect this project."}],
                "react_single",
                "dante",
                workspace=str(workspace),
            )
            self.assertEqual(Path(harness.workspace).resolve(), workspace)
            self.assertEqual(
                Path(harness.session.save_dir).resolve().parent,
                Path(__file__).resolve().parents[1] / "sessions",
            )
            self.assertTrue(harness.agents)
            for agent in harness.agents.values():
                self.assertEqual(Path(agent.workspace).resolve(), workspace)

    @patch('product_features.require_flow')
    def test_adaptive_code_agent_explicitly_omits_per_response_token_cap(self, _development_branch_gate):
        with tempfile.TemporaryDirectory() as directory:
            harness, _slots = _build_chat_harness(
                [],
                "adaptive_code_agent",
                "coder",
                workspace=directory,
            )

            self.assertTrue(harness.agents)
            self.assertTrue(all(agent.llm.max_tokens is None for agent in harness.agents.values()))
            primary = harness.agents["agent"]
            self.assertEqual(primary.identity.ID["name"], "deepseek_operator")
            visible = {item["function"]["name"] for item in primary.get_tools_desc()}
            self.assertTrue({"web_search", "fetch_urls", "browser"}.issubset(visible))


if __name__ == "__main__":
    unittest.main()
