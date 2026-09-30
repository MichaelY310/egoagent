from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent
from message_protocol import compose_model_messages


class IdentityCompositionTests(unittest.TestCase):
    def test_composite_identity_inherits_multiple_ego_capability_packs(self):
        agent = Agent(ROOT / "identity" / "openmanus", workspace=ROOT)
        tools = {agent._short_name(name) for name in agent.tools}

        self.assertIn("read_file", tools)
        self.assertIn("run_command", tools)
        self.assertIn("web_search", tools)
        self.assertIn("fetch_url", tools)
        self.assertIn("fetch_urls", tools)
        self.assertIn("browser", tools)
        self.assertEqual(agent.identity.ID["name"], "openmanus")

        visible = {item["function"]["name"] for item in agent.get_tools_desc()}
        self.assertTrue({"browser", "web_search", "fetch_url", "fetch_urls"}.issubset(visible))

    def test_identity_and_dag_policy_keep_distinct_system_sections(self):
        agent = Agent(ROOT / "identity" / "openmanus", workspace=ROOT)
        identity_prompt = agent.build_system_prompt(has_tools=True)
        converted = agent._convert_messages_for_llm([
            {"role": "user", "content": "perform the task"},
            {"role": "system", "name": "context_summary", "content": "verified prior state"},
            {"role": "system", "name": "dag_instruction", "content": "use the review branch"},
        ])
        request = compose_model_messages(identity_prompt, converted)

        self.assertEqual([message["role"] for message in request], ["system", "user"])
        system = request[0]["content"]
        self.assertTrue(system.startswith("You are openmanus"))
        self.assertIn(agent.identity.ID["description"], system)
        self.assertIn("[context_summary]\nverified prior state", system)
        self.assertIn("[dag_instruction]\nuse the review branch", system)
        self.assertLess(system.index(agent.identity.ID["description"]), system.index("[dag_instruction]"))
        self.assertEqual(request[1]["content"], "perform the task")

    def test_node_tool_allowlist_is_applied_before_global_prompt_budget(self):
        agent = Agent(ROOT / "identity" / "adaptive_deepseek_coder", workspace=ROOT)
        requested = {
            "activate_capability",
            "create_knowledge",
            "create_skill",
            "create_agent_system",
            "manage_harness",
        }

        visible = {
            item["function"]["name"]
            for item in agent.get_tools_desc(include_tools=sorted(requested))
        }

        self.assertTrue(requested.issubset(visible))


if __name__ == "__main__":
    unittest.main()
