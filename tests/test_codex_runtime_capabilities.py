from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from environment import load_tool_from_dir
from harness_editor import change_tracker
from pipeline_schema import validate_pipeline


PACK = ROOT / "capability_packs" / "codex_runtime" / "skills"


def call_tool(name: str, arguments: dict, context: dict):
    tool = load_tool_from_dir(PACK / name, prefix="")
    assert tool is not None and tool.func is not None
    return json.loads(tool.func(**arguments, _context=context))


class CodexRuntimeCapabilityTests(unittest.TestCase):
    def test_codex_identity_and_flow_are_valid_and_expose_runtime_tools(self):
        from agent import Agent

        config = json.loads((ROOT / "harness" / "codex_flow" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_pipeline(config["pipeline"]), [])
        agent = Agent(ROOT / "identity" / "codex_operator", workspace=ROOT)
        names = {agent._short_name(name) for name in agent.tools}
        self.assertTrue({"apply_patch", "exec_command", "write_stdin", "update_plan"}.issubset(names))

    def test_arc_long_horizon_flow_is_valid_and_exposes_only_adapter_capabilities(self):
        from agent import Agent

        config = json.loads((ROOT / "harness" / "arc_long_horizon" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_pipeline(config["pipeline"]), [])
        agent = Agent(ROOT / "identity" / "arc_explorer", workspace=ROOT)
        names = {agent._short_name(name) for name in agent.tools}
        self.assertTrue({"arc_start", "arc_act", "arc_status", "arc_finish"}.issubset(names))

    def test_apply_patch_updates_adds_and_deletes_as_one_reviewable_operation(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            store = workspace / "changes.json"
            change_tracker.configure_store(store, load=True)
            (workspace / "update.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            (workspace / "delete.txt").write_text("remove\n", encoding="utf-8")
            patch = """*** Begin Patch
*** Update File: update.txt
@@
 alpha
-beta
+gamma
*** Add File: added.txt
+new file
*** Delete File: delete.txt
*** End Patch"""

            result = call_tool("apply_patch", {"patch": patch}, {"workspace": str(workspace)})

            self.assertTrue(result["ok"], result)
            self.assertEqual((workspace / "update.txt").read_text(encoding="utf-8"), "alpha\ngamma\n")
            self.assertEqual((workspace / "added.txt").read_text(encoding="utf-8"), "new file")
            self.assertFalse((workspace / "delete.txt").exists())
            self.assertEqual(len(result["files"]), 3)
        change_tracker.configure_store(None, load=True)

    def test_apply_patch_rejects_workspace_escape_before_writing(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            result = call_tool(
                "apply_patch",
                {"patch": "*** Begin Patch\n*** Add File: ../escape.txt\n+no\n*** End Patch"},
                {"workspace": temporary},
            )
            self.assertFalse(result["ok"])
            self.assertIn("escapes workspace", result["error"])

    def test_exec_command_supports_incremental_stdin_and_output(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            registry = {}
            context = {"workspace": temporary, "running_commands": registry, "sandbox": {"mode": "workspace"}}
            code = "import sys; print('ready', flush=True); value=sys.stdin.readline().strip(); print('got:'+value, flush=True)"
            command = f'"{sys.executable}" -u -c "{code}"'
            started = call_tool("exec_command", {"cmd": command, "yield_time_ms": 200}, context)
            self.assertIn(started["status"], {"running", "done"}, started)
            self.assertIn("ready", started["output"])
            self.assertEqual(started["status"], "running", started)

            finished = call_tool(
                "write_stdin",
                {"session_id": started["session_id"], "chars": "ping\n", "yield_time_ms": 2000},
                context,
            )
            self.assertEqual(finished["status"], "done", finished)
            self.assertEqual(finished["exit_code"], 0)
            self.assertIn("got:ping", finished["output"])

    def test_update_plan_rejects_two_active_items_and_persists_valid_state(self):
        state = {}
        context = {"plan_state": state}
        invalid = call_tool("update_plan", {"plan": [
            {"step": "one", "status": "in_progress"},
            {"step": "two", "status": "in_progress"},
        ]}, context)
        self.assertFalse(invalid["ok"])
        valid = call_tool("update_plan", {"plan": [
            {"step": "one", "status": "completed"},
            {"step": "two", "status": "in_progress"},
        ], "explanation": "progress"}, context)
        self.assertTrue(valid["ok"])
        self.assertEqual(state["items"][1]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
