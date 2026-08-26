from __future__ import annotations

import time
import unittest
import shutil
from pathlib import Path

import harness_editor.server as server_module


ROOT = Path(__file__).resolve().parents[1]


class InteractiveRuntimeStartupTests(unittest.TestCase):
    def test_real_chat_harness_reaches_waiting_input_before_first_message(self):
        existing_sessions = {item.resolve() for item in (ROOT / "sessions").glob("react_single_*")}
        handle = server_module.interactive_execution.start(
            workspace=ROOT / "tutorial_assets" / "video_demo_repo",
            harness="react_single",
            agents={"agent": "identity/test_bot"},
            debug_mode="auto",
            mode="chat",
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
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not handle.state.get("waiting_for_input"):
                if not handle.state.get("running"):
                    break
                time.sleep(0.02)
            self.assertTrue(handle.state.get("running"), handle.snapshot(include_outputs=True))
            self.assertTrue(handle.state.get("waiting_for_input"), handle.snapshot(include_outputs=True))
            self.assertEqual(handle.state.get("current_node"), "wait_input")
        finally:
            if handle.state.get("running"):
                server_module.interactive_execution.stop({"run_id": handle.run_id})
            if handle.thread:
                handle.thread.join(timeout=3)
            if not handle.state.get("running"):
                server_module.interactive_runs.remove(handle.run_id)
            for session_dir in (ROOT / "sessions").glob("react_single_*"):
                if session_dir.resolve() not in existing_sessions:
                    shutil.rmtree(session_dir)


if __name__ == "__main__":
    unittest.main()
