from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent
from harness import Harness, runtime_scope
from llm.conformance_server import ProviderConformanceServer
from llm.custom_llm import CustomLLM
from llm.providers import AnthropicCompatibleLLM, create_provider, probe_model


def config(base_url, **overrides):
    value = {
        "base_url": base_url,
        "model": "mock-model",
        "api_key": "mock-secret",
        "max_retries": 1,
        "retry_backoff": 0,
        "timeout": 2,
    }
    value.update(overrides)
    return value


class ProviderConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_patch = patch.dict(os.environ, {
            "EGOAGENT_LLM_BASE_URL": "",
            "EGOAGENT_LLM_MODEL": "",
            "EGOAGENT_LLM_API_KEY": "",
            "EGOAGENT_LLM_TIMEOUT": "",
            "EGOAGENT_LLM_MAX_RETRIES": "",
            "EGOAGENT_LLM_RETRY_BACKOFF": "",
            "EGOAGENT_LLM_ENABLE_THINKING": "",
            "DEEPSEEK_API_KEY": "",
            "SILICONFLOW_API_KEY": "",
        })
        cls.env_patch.start()
        cls.server = ProviderConformanceServer().start()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.env_patch.stop()

    def test_openai_probe_covers_text_stream_json_tools_reasoning_and_usage(self):
        client = CustomLLM(config(self.server.base_url))
        result = probe_model(client).as_dict()

        self.assertTrue(result["healthy"])
        for role in ("chat", "tool_use", "edit", "apply", "autocomplete", "reasoning"):
            self.assertTrue(result["capabilities"][role], role)
        self.assertFalse(result["capabilities"]["embedding"])
        self.assertTrue(all(check["ok"] for check in result["checks"].values()))
        self.assertEqual(result["usage"]["prompt_tokens_details"]["cached_tokens"], 3)

    def test_real_http_retry_429_timeout_and_multiple_tools(self):
        client = CustomLLM(config(self.server.base_url, timeout=0.05))
        response = client.chat([{"role": "user", "content": "[retry-once] hello"}])
        self.assertEqual(response["choices"][0]["message"]["content"], "ego-probe-ok")
        self.assertEqual(client.last_response_metadata["attempts"], 2)
        self.assertEqual(client.last_response_metadata["retries"], 1)

        tools = [{"type": "function", "function": {"name": "ego_probe_echo", "parameters": {"type": "object"}}}]
        response = client.chat(
            [{"role": "user", "content": "[multi-tool] call twice"}], tools=tools, tool_choice="required"
        )
        self.assertEqual(len(response["choices"][0]["message"]["tool_calls"]), 2)

        timeout_client = CustomLLM(config(self.server.base_url, timeout=0.02, max_retries=0))
        with self.assertRaises(requests.Timeout):
            timeout_client.chat([{"role": "user", "content": "[timeout]"}])

    def test_anthropic_adapter_translates_messages_tools_stream_and_cache_usage(self):
        client = AnthropicCompatibleLLM(config(self.server.base_url, provider="anthropic"))
        result = probe_model(client, "anthropic_compatible").as_dict()

        self.assertTrue(result["healthy"])
        self.assertTrue(result["capabilities"]["tool_use"])
        self.assertTrue(result["capabilities"]["edit"])
        self.assertTrue(result["capabilities"]["reasoning"])
        self.assertEqual(client.last_response_metadata["usage"]["prompt_tokens_details"]["cached_tokens"], 3)

        followup = client.chat([
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "ego_probe_echo", "arguments": '{"value":"one"}'},
            }]},
            {"role": "tool", "tool_call_id": "call_1", "content": "one"},
            {"role": "user", "content": "finish"},
        ])
        self.assertEqual(followup["choices"][0]["message"]["content"], "ego-probe-ok")
        path, payload = self.server.httpd.last_payloads[-1]
        self.assertEqual(path, "/v1/messages")
        self.assertEqual(payload["messages"][0]["content"][0]["type"], "tool_use")
        self.assertEqual(payload["messages"][1]["content"][0]["type"], "tool_result")

    def test_factory_normalizes_keyless_ollama_and_selects_anthropic(self):
        ollama = create_provider({"type": "ollama", "model": "tiny", "base_url": "http://127.0.0.1:11434"})
        self.assertIsInstance(ollama, CustomLLM)
        self.assertEqual(ollama.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(ollama.api_key, "ollama-local")
        anthropic = create_provider(config(self.server.base_url, type="anthropic"))
        self.assertIsInstance(anthropic, AnthropicCompatibleLLM)

    def test_studio_probe_exposes_health_and_disables_unsupported_roles(self):
        from harness_editor import ai_service

        with patch.dict(os.environ, {
            "EGOAGENT_LLM_PROVIDER": "openai_compatible",
            "EGOAGENT_LLM_BASE_URL": self.server.base_url,
            "EGOAGENT_LLM_MODEL": "mock-model",
            "EGOAGENT_LLM_API_KEY": "mock-secret",
            "EGOAGENT_LLM_TIMEOUT": "2",
            "EGOAGENT_LLM_MAX_RETRIES": "1",
        }):
            ai_service._last_probe = None
            probed = ai_service.run_ai_operation("probe", {})
            status = ai_service.get_ai_status()
            self.assertTrue(probed["healthy"])
            self.assertTrue(status["health"])
            self.assertTrue(status["capabilities"]["autocomplete"])
            completion = ai_service.run_ai_operation(
                "completion",
                {"prefix": "def demo():\n    ", "suffix": "", "language": "python", "path": "demo.py"},
            )
            self.assertEqual(completion["completion"], "mock completion")

            ai_service._last_probe = {
                **probed,
                "healthy": True,
                "capabilities": {**probed["capabilities"], "autocomplete": False},
            }
            with self.assertRaisesRegex(ai_service.AIServiceError, "autocomplete"):
                ai_service.run_ai_operation("completion", {"prefix": "x", "suffix": ""})

    def test_malformed_failed_and_denied_calls_each_receive_one_tool_result(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            workspace = Path(directory)
            marker = workspace / ".egoagent"
            marker.mkdir()
            (marker / "environment.json").write_text("{}", encoding="utf-8")
            agent = Agent(ROOT / "identity" / "dante", workspace=workspace)
            harness = Harness(
                ROOT / "harness" / "react_single",
                agents={"agent": agent},
                workspace=workspace,
            )
            cases = [
                {"id": "bad", "function": {"name": "read_file", "arguments": "not-json"}},
                {"id": "missing", "function": {"name": "does_not_exist", "arguments": "{}"}},
                {"id": "denied", "function": {"name": "read_file", "arguments": json.dumps({"file_path": str(ROOT / ".env.local")})}},
            ]
            with runtime_scope(harness=harness):
                for call in cases:
                    harness.session.record({"role": "assistant", "name": "agent", "content": "", "tool_calls": [call]})
                    before = len([m for m in harness.session.messages if "<tool_response>" in str(m.get("content", ""))])
                    agent.execute_tool_call(call)
                    after = len([m for m in harness.session.messages if "<tool_response>" in str(m.get("content", ""))])
                    self.assertEqual(after - before, 1, call["id"])
            converted = agent._convert_messages_for_llm(harness.session.messages)
            tool_results = [message for message in converted if message.get("role") == "tool"]
            self.assertEqual(len(tool_results), len(cases))
            self.assertEqual(
                {message["tool_call_id"] for message in tool_results},
                {case["id"] for case in cases},
            )


if __name__ == "__main__":
    unittest.main()
