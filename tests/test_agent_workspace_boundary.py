from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent, _console_write
from harness import Harness, set_current_harness
from harness_editor.change_tracker import configure_store, get_transaction_summary


def _call(name: str, arguments: dict) -> dict:
    return {
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        }
    }


class AgentWorkspaceBoundaryTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.workspace = Path(self.temp.name)
        marker = self.workspace / ".egoagent"
        marker.mkdir()
        (marker / "environment.json").write_text(
            json.dumps({"backend": "local", "network": "disabled"}),
            encoding="utf-8",
        )
        (self.workspace / "inside.txt").write_text("safe", encoding="utf-8")
        self.agent = Agent(ROOT / "identity" / "dante", workspace=self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def test_task_workspace_allows_relative_reads(self):
        result = self.agent.execute_tool_call(_call("read_file", {"file_path": "inside.txt"}))
        self.assertEqual(result, "safe")

    def test_task_workspace_rejects_absolute_reads_outside_root(self):
        result = self.agent.execute_tool_call(
            _call("read_file", {"file_path": str(ROOT / ".env.local")})
        )
        self.assertIn("Permission denied", result)
        self.assertIn("must stay inside", result)

    def test_task_workspace_confines_path_arguments_of_evolved_tools(self):
        denied = self.agent._check_workspace_path_access(
            "generated_normalizer",
            {"legacy_path": "inside.txt", "output_path": "../escaped.json"},
        )
        self.assertIn("output_path", denied)
        allowed = self.agent._check_workspace_path_access(
            "generated_normalizer",
            {"legacy_path": "inside.txt", "output_path": "nested/output.json"},
        )
        self.assertIsNone(allowed)

    def test_activated_skill_direct_writes_enter_change_review_transaction(self):
        source = ROOT / "identity" / "dante" / "ego" / "skills" / "read_file"
        found = ("tool", SimpleNamespace(source_path=str(source)))
        self.agent._activated_capability_refs = {
            "skill:test": SimpleNamespace(source=str(source), kind="skill")
        }
        store = self.workspace / "change-journal.json"
        configure_store(store)
        try:
            before = self.agent._activated_capability_workspace_snapshot(found)
            (self.workspace / "generated.txt").write_text("created by skill\n", encoding="utf-8")
            self.agent._record_activated_capability_workspace_changes(before, found, "generated_skill")
            summary = get_transaction_summary("unscoped")
        finally:
            configure_store(None)

        self.assertEqual(summary["files"], 1)
        self.assertEqual(summary["hunks"], 1)
        self.assertEqual(summary["changes"][0]["tool_name"], "generated_skill")
        self.assertTrue(summary["changes"][0]["is_new_file"])

    def test_denied_windows_path_still_completes_deepseek_tool_protocol(self):
        harness = Harness(
            ROOT / "harness" / "react_single",
            agents={"agent": self.agent},
            workspace=self.workspace,
        )
        assistant_message = {
            "role": "assistant",
            "content": (
                '<tool_call>{"name":"read_file","arguments":'
                '{"file_path":"C:\\\\Users\\\\outside.txt"}}</tool_call>'
            ),
        }
        harness.session.record(assistant_message)
        try:
            set_current_harness(harness)
            result = self.agent.execute_tool_call(
                _call("read_file", {"file_path": "C:\\Users\\outside.txt"})
            )
        finally:
            set_current_harness(None)

        self.assertIn("Permission denied", result)
        converted = self.agent._convert_messages_for_llm(harness.session.messages)
        self.assertEqual(converted[-2]["role"], "assistant")
        self.assertEqual(converted[-1]["role"], "tool")
        self.assertEqual(
            converted[-1]["tool_call_id"],
            converted[-2]["tool_calls"][0]["id"],
        )

    def test_model_tool_ids_survive_compact_session_round_trip(self):
        class ToolLLM:
            def chat_stream(self, messages, tools=None):
                yield {"tool_calls": [{
                    "id": "provider_call_exact",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"file_path":"inside.txt"}'},
                }]}

        harness = Harness(
            ROOT / "harness" / "react_single",
            agents={"agent": self.agent},
            workspace=self.workspace,
        )
        self.agent.llm = ToolLLM()
        try:
            set_current_harness(harness)
            _, calls = self.agent.step([], tools_desc=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}])
            self.agent.execute_tool_call(calls[0])
        finally:
            set_current_harness(None)

        self.assertEqual(harness.session.messages[0]["tool_calls"][0]["id"], "provider_call_exact")
        converted = self.agent._convert_messages_for_llm(harness.session.messages)
        self.assertEqual(converted[-2]["tool_calls"][0]["id"], "provider_call_exact")
        self.assertEqual(converted[-1]["tool_call_id"], "provider_call_exact")

    def test_shared_subdag_tool_transaction_becomes_plain_context_for_parent_agent(self):
        messages = [
            {"role": "user", "content": "inspect the project"},
            {
                "role": "assistant",
                "name": "searcher",
                "content": '<tool_call>{"name":"search_capabilities","arguments":{"query":"inspect"}}</tool_call>',
                "tool_calls": [{
                    "id": "foreign-call-1",
                    "type": "function",
                    "function": {"name": "search_capabilities", "arguments": '{"query":"inspect"}'},
                }],
            },
            {
                "role": "user",
                "content": '<tool_response>{"tool":"search_capabilities","tool_call_id":"foreign-call-1","content":"matched read_file"}</tool_response>',
            },
            {"role": "assistant", "name": "searcher", "content": "Use read_file."},
        ]

        converted = self.agent._convert_messages_for_llm(messages)

        self.assertFalse(any(message.get("role") == "tool" for message in converted))
        self.assertFalse(any(message.get("tool_calls") for message in converted))
        self.assertTrue(any("Tool result for agent searcher" in message.get("content", "") for message in converted))

    def test_orphan_and_incomplete_tool_history_is_downgraded_not_sent_to_provider(self):
        orphan = self.agent._convert_messages_for_llm([{
            "role": "user",
            "content": '<tool_response>{"tool":"read_file","tool_call_id":"missing","content":"old result"}</tool_response>',
        }])
        self.assertEqual(orphan[0]["role"], "user")
        self.assertIn("Unpaired tool observation", orphan[0]["content"])

        incomplete = Agent._sanitize_tool_protocol([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "one", "function": {"name": "read_file", "arguments": "{}"}},
                    {"id": "two", "function": {"name": "search_files", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "one", "content": "partial"},
            {"role": "user", "content": "next turn"},
        ])
        self.assertFalse(any(message.get("role") == "tool" for message in incomplete))
        self.assertFalse(any(message.get("tool_calls") for message in incomplete))

    def test_non_ascii_model_progress_cannot_crash_a_legacy_windows_pipe(self):
        raw = io.BytesIO()
        legacy = io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
        original = sys.stdout
        try:
            sys.stdout = legacy
            _console_write("中文进度")
        finally:
            sys.stdout = original
        self.assertIn(b"\\u", raw.getvalue())

    def test_task_workspace_rejects_nested_harness_workspace_escape(self):
        result = self.agent.execute_tool_call(
            _call(
                "create_harness",
                {
                    "harness_dir": "harness/react_single",
                    "agents": "agent:identity/dante",
                    "workspace": str(ROOT),
                },
            )
        )
        self.assertIn("Permission denied", result)

    def test_regular_ide_workspace_keeps_normal_project_access(self):
        regular = Agent(ROOT / "identity" / "dante", workspace=self.workspace / "regular")
        self.assertIsNone(
            regular._check_workspace_path_access(
                "read_file", {"file_path": str(ROOT / "README.md")}
            )
        )

    def test_parallel_agents_write_relative_paths_without_changing_process_cwd(self):
        other_workspace = self.workspace / "other"
        other_workspace.mkdir()
        marker = other_workspace / ".egoagent"
        marker.mkdir()
        (marker / "environment.json").write_text(
            json.dumps({"backend": "local", "network": "disabled"}),
            encoding="utf-8",
        )
        other_agent = Agent(ROOT / "identity" / "dante", workspace=other_workspace)
        original_cwd = os.getcwd()
        barrier = threading.Barrier(2)
        results = []

        def write(agent, content):
            barrier.wait(timeout=5)
            results.append(
                agent.execute_tool_call(
                    _call("write_file", {"file_path": "same.txt", "content": content})
                )
            )

        threads = [
            threading.Thread(target=write, args=(self.agent, "workspace-a")),
            threading.Thread(target=write, args=(other_agent, "workspace-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(os.getcwd(), original_cwd)
        self.assertEqual((self.workspace / "same.txt").read_text(encoding="utf-8"), "workspace-a")
        self.assertEqual((other_workspace / "same.txt").read_text(encoding="utf-8"), "workspace-b")
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
