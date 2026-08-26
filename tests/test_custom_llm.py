import unittest
from unittest.mock import patch

import requests

from agent import Agent
from llm.custom_llm import CustomLLM


class FakeResponse:
    def __init__(self, *, status=200, headers=None, payload=None, lines=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload or {}
        self._lines = list(lines or [])
        self.text = text
        self.encoding = None
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def iter_lines(self, decode_unicode=True):
        for line in self._lines:
            if isinstance(line, BaseException):
                raise line
            yield line


def llm_config(**overrides):
    config = {
        "base_url": "https://provider.invalid/v1",
        "model": "test-model",
        "max_retries": 1,
        "retry_backoff": 0,
    }
    config.update(overrides)
    return config


class CustomLLMResilienceTests(unittest.TestCase):
    def test_deepseek_tool_payload_omits_incompatible_thinking_mode(self):
        llm = CustomLLM(llm_config(base_url="https://api.deepseek.com", enable_thinking=True))
        without_tools = llm._build_payload([], tools=None)
        with_tools = llm._build_payload([], tools=[{"type": "function"}])
        self.assertEqual(without_tools["thinking"], {"type": "enabled"})
        self.assertNotIn("thinking", with_tools)

        normal = CustomLLM(llm_config(base_url="https://api.deepseek.com", enable_thinking=False))
        self.assertEqual(normal._build_payload([{"role": "user", "content": "x"}])["thinking"], {"type": "disabled"})
        self.assertEqual(
            normal._build_payload([{"role": "user", "content": "x"}], tools=[{"type": "function"}])["thinking"],
            {"type": "disabled"},
        )

    def test_legacy_identity_routed_to_deepseek_disables_default_thinking(self):
        llm = CustomLLM(llm_config(base_url="https://api.deepseek.com", model="deepseek-v4-flash"))

        self.assertFalse(llm.enable_thinking)
        self.assertEqual(
            llm._build_payload([{"role": "user", "content": "x"}])["thinking"],
            {"type": "disabled"},
        )

    @patch("llm.custom_llm.requests.post")
    def test_stream_preserves_hidden_reasoning_for_deepseek_tool_continuation(self, post):
        post.return_value = FakeResponse(lines=[
            'data: {"choices":[{"delta":{"reasoning_content":"hidden plan"}}]}',
            "",
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"read_file","arguments":"{\\\"file_path\\\":\\\"a.txt\\\"}"}}]}}]}',
            "",
            "data: [DONE]",
            "",
        ])
        llm = CustomLLM(llm_config(base_url="https://api.deepseek.com"))

        deltas = list(llm.chat_stream([{"role": "user", "content": "read"}], tools=[{"type": "function"}]))

        self.assertEqual("".join(str(delta.get("reasoning_content", "")) for delta in deltas), "hidden plan")
        self.assertEqual(deltas[-1]["tool_calls"][0]["function"]["name"], "read_file")

    @patch("llm.custom_llm.requests.post")
    def test_stream_captures_length_finish_reason(self, post):
        post.return_value = FakeResponse(lines=[
            'data: {"choices":[{"delta":{"content":"partial"}}]}',
            "",
            'data: {"choices":[{"delta":{},"finish_reason":"length"}],"usage":{"completion_tokens":8}}',
            "",
            "data: [DONE]",
            "",
        ])
        llm = CustomLLM(llm_config())

        self.assertEqual("".join(delta.get("content", "") for delta in llm.chat_stream([])), "partial")
        self.assertEqual(llm.last_response_metadata["finish_reason"], "length")
        self.assertTrue(llm.last_response_metadata["output_truncated"])

    def test_agent_adds_visible_notice_and_drops_partial_tools_on_truncation(self):
        class TruncatedLLM:
            def __init__(self):
                self.last_response_metadata = {}

            def chat_stream(self, messages, tools=None):
                yield {"content": "unfinished sentence"}
                yield {"tool_calls": [{
                    "id": "partial-call",
                    "function": {"name": "read_file", "arguments": '{"file_path":'},
                }]}
                self.last_response_metadata = {
                    "sequence": 1,
                    "finish_reason": "length",
                    "output_truncated": True,
                }

        agent = object.__new__(Agent)
        agent.name = "agent"
        agent.llm = TruncatedLLM()
        agent.hooks = {"pre_llm_hook": None, "post_llm_hook": None}
        agent.build_system_prompt = lambda has_tools=False: ""
        streamed = []

        text, calls = agent.step([], tools_desc=[], on_token=streamed.append)

        self.assertIn("输出长度上限", text)
        self.assertIn("输出长度上限", "".join(streamed))
        self.assertFalse(calls)

    def test_agent_round_trip_keeps_reasoning_off_visible_content(self):
        agent = object.__new__(Agent)
        agent.name = "agent"
        converted = agent._convert_messages_for_llm([
            {
                "role": "assistant",
                "name": "agent",
                "content": '<tool_call>{"name":"read_file","arguments":{"file_path":"a.txt"}}</tool_call>',
                "reasoning_content": "hidden plan",
            },
            {
                "role": "user",
                "content": '<tool_response>{"tool":"read_file","content":"ok"}</tool_response>',
            },
        ])
        self.assertEqual(converted[0]["reasoning_content"], "hidden plan")
        self.assertIsNone(converted[0]["content"])
        self.assertEqual(converted[1]["role"], "tool")

    @patch("llm.custom_llm.requests.post")
    def test_chat_honors_retry_after_and_captures_provider_usage(self, post):
        post.side_effect = [
            FakeResponse(status=429, headers={"Retry-After": "0"}, text="busy"),
            FakeResponse(
                headers={"x-request-id": "req-success"},
                payload={
                    "id": "completion-1",
                    "model": "served-model",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 3,
                        "prompt_tokens_details": {"cached_tokens": 7},
                    },
                },
            ),
        ]
        llm = CustomLLM(llm_config())

        result = llm.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(llm.last_response_metadata["provider_request_id"], "req-success")
        self.assertEqual(llm.last_response_metadata["attempts"], 2)
        self.assertEqual(llm.last_response_metadata["retries"], 1)
        self.assertEqual(llm.last_response_metadata["usage"]["prompt_tokens"], 11)

    @patch("llm.custom_llm.requests.post")
    def test_stream_resumes_from_event_id_without_replaying_content(self, post):
        first = FakeResponse(
            headers={"x-request-id": "stream-1"},
            lines=[
                "id: 1",
                'data: {"choices":[{"delta":{"content":"A"}}]}',
                "",
                requests.ConnectionError("socket dropped"),
            ],
        )
        second = FakeResponse(
            headers={"x-request-id": "stream-2"},
            lines=[
                "id: 1",
                'data: {"choices":[{"delta":{"content":"A"}}]}',
                "",
                "id: 2",
                'data: {"choices":[{"delta":{"content":"B"}}]}',
                "",
                'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
                "",
                "data: [DONE]",
                "",
            ],
        )
        post.side_effect = [first, second]
        llm = CustomLLM(llm_config(stream_resume=True))

        deltas = list(llm.chat_stream([{"role": "user", "content": "hello"}]))

        self.assertEqual("".join(delta.get("content", "") for delta in deltas), "AB")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[1].kwargs["headers"]["Last-Event-ID"], "1")
        self.assertEqual(llm.last_response_metadata["reconnects"], 1)
        self.assertEqual(llm.last_response_metadata["provider_request_ids"], ["stream-1", "stream-2"])
        self.assertEqual(llm.last_response_metadata["usage"]["completion_tokens"], 2)

    @patch("llm.custom_llm.requests.post")
    def test_stream_refuses_unsafe_replay_without_event_id(self, post):
        post.return_value = FakeResponse(
            lines=[
                'data: {"choices":[{"delta":{"content":"A"}}]}',
                "",
                requests.ConnectionError("socket dropped"),
            ]
        )
        llm = CustomLLM(llm_config(stream_resume=True))

        with self.assertRaisesRegex(requests.ConnectionError, "no SSE event id"):
            list(llm.chat_stream([{"role": "user", "content": "hello"}]))

        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
