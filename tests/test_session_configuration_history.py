from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness import Session


class SessionConfigurationHistoryTests(unittest.TestCase):
    def test_each_message_keeps_its_speaker_and_configuration_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = Session(workspace=root, save_dir=root / "session")
            first = session.set_agent_config({
                "harness": "research_flow",
                "agents": {"researcher": "identity/researcher"},
                "mode": "chat",
                "debug_mode": "auto",
                "mutation_targets": [],
            }, run_id="run-1")
            session.record({"role": "user", "content": "find evidence"})
            session.record({"role": "assistant", "name": "researcher", "content": "evidence"})

            second = session.set_agent_config({
                "harness": "code_flow",
                "agents": {"coder": "identity/dante"},
                "mode": "agent",
                "debug_mode": "auto",
                "mutation_targets": [],
            }, run_id="run-2")
            session.record({"role": "assistant", "name": "coder", "content": "patch"})
            session.save()

            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(session.messages[0]["_speaker"]["kind"], "user")
            self.assertEqual(session.messages[1]["_speaker"]["agent"], "researcher")
            self.assertEqual(session.messages[1]["_agent_config"]["harness"], "research_flow")
            self.assertEqual(session.messages[2]["_speaker"]["agent"], "coder")
            self.assertEqual(session.messages[2]["_agent_config"]["harness"], "code_flow")
            self.assertEqual(len(session.agent_config["history"]), 1)

            metadata = json.loads((root / "session" / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["agent_config"]["revision"], 2)
            self.assertEqual(metadata["agent_config"]["history"][0]["harness"], "research_flow")


if __name__ == "__main__":
    unittest.main()
