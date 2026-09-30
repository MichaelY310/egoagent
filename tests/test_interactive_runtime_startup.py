from __future__ import annotations

import json
import time
import unittest
import shutil
import uuid
from pathlib import Path

import harness_editor.server as server_module
from harness import Session


ROOT = Path(__file__).resolve().parents[1]


class InteractiveRuntimeStartupTests(unittest.TestCase):
    def test_chat_prompt_maps_to_autonomous_component_input_ports(self):
        config = json.loads((ROOT / "harness" / "component_capability_discovery" / "config.json").read_text(encoding="utf-8"))
        seeded = server_module._interactive_seed_data(config, "find a reusable browser flow", {})
        self.assertEqual(seeded["request"], "find a reusable browser flow")
        self.assertEqual(seeded["task"], "find a reusable browser flow")
        self.assertEqual(seeded["query"], "find a reusable browser flow")
        self.assertEqual(seeded["max_tool_rounds"], 3)

    def test_real_chat_harness_reaches_waiting_input_before_first_message(self):
        existing_sessions = {item.resolve() for item in (ROOT / "sessions").glob("react_single_*")}
        handle = server_module.interactive_execution.start(
            workspace=ROOT / "tutorial_assets" / "video_demo_repo",
            harness="react_single",
            agents={"agent": "identity/test_bot"},
            debug_mode="auto",
            mode="chat",
            surface="chat",
            mutation_targets=[],
            security={},
            sandbox={},
            worker_target=server_module._run_harness_in_thread,
            worker_args=lambda created: (
                "react_single",
                {"agent": "identity/test_bot"},
                created.input_queue,
                created.run_id,
                str(ROOT / "tutorial_assets" / "video_demo_repo"),
                "chat",
                (),
            ),
        )
        session_name = ""
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not handle.state.get("waiting_for_input"):
                if not handle.state.get("running"):
                    break
                time.sleep(0.02)
            self.assertTrue(handle.state.get("running"), handle.snapshot(include_outputs=True))
            self.assertTrue(handle.state.get("waiting_for_input"), handle.snapshot(include_outputs=True))
            self.assertEqual(handle.state.get("current_node"), "wait_input")
            session_name = str(handle.state.get("session_name") or "")
            self.assertTrue(session_name)
            self.assertEqual(handle.state.get("surface"), "chat")
        finally:
            if handle.state.get("running"):
                server_module.interactive_execution.stop({"run_id": handle.run_id})
            if handle.thread:
                handle.thread.join(timeout=3)
            if session_name:
                metadata = json.loads((ROOT / "sessions" / session_name / "session.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["agent_config"]["harness"], "react_single")
                self.assertEqual(metadata["agent_config"]["agents"], {"agent": "identity/test_bot"})
                self.assertEqual(metadata["agent_config"]["mode"], "chat")
            if not handle.state.get("running"):
                server_module.interactive_runs.remove(handle.run_id)
            for session_dir in (ROOT / "sessions").glob("react_single_*"):
                if session_dir.resolve() not in existing_sessions:
                    shutil.rmtree(session_dir)

    def test_reconfiguration_resumes_one_durable_session_with_a_new_flow_revision(self):
        workspace = ROOT / "tutorial_assets" / "video_demo_repo"
        session_dir = ROOT / "sessions" / f"resume_config_{uuid.uuid4().hex[:10]}"
        original = Session(workspace=workspace, save_dir=session_dir)
        original.set_agent_config({
            "harness": "previous_flow",
            "agents": {"agent": "identity/test_bot"},
            "mode": "plan",
            "debug_mode": "auto",
            "mutation_targets": [],
        }, run_id="old-run")
        original.record({"role": "user", "content": "first turn"})
        original.record({"role": "assistant", "name": "agent", "content": "first answer"})
        original.save()

        handle = server_module.interactive_execution.start(
            workspace=workspace,
            harness="react_single",
            agents={"agent": "identity/test_bot"},
            debug_mode="auto",
            mode="chat",
            surface="chat",
            mutation_targets=[],
            security={},
            sandbox={},
            session_name=session_dir.name,
            worker_target=server_module._run_harness_in_thread,
            worker_args=lambda created: (
                "react_single",
                {"agent": "identity/test_bot"},
                created.input_queue,
                created.run_id,
                str(workspace),
                "chat",
                (),
                session_dir.name,
                "",
                {},
            ),
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not handle.state.get("waiting_for_input"):
                if not handle.state.get("running"):
                    break
                time.sleep(0.02)
            self.assertTrue(handle.state.get("waiting_for_input"), handle.snapshot(include_outputs=True))
            self.assertEqual(handle.state.get("session_name"), session_dir.name)
        finally:
            if handle.state.get("running"):
                server_module.interactive_execution.stop({"run_id": handle.run_id, "wait": True})
            if not handle.state.get("running"):
                server_module.interactive_runs.remove(handle.run_id)

        metadata = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        messages = json.loads((session_dir / "messages.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["agent_config"]["harness"], "react_single")
        self.assertEqual(metadata["agent_config"]["revision"], 2)
        self.assertEqual(metadata["agent_config"]["history"][0]["harness"], "previous_flow")
        self.assertEqual([item["content"] for item in messages[:2]], ["first turn", "first answer"])
        shutil.rmtree(session_dir)


if __name__ == "__main__":
    unittest.main()
