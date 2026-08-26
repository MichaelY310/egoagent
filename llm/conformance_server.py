"""Local OpenAI/Anthropic-compatible fault-injection server for tests and demos."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _json(self, status, payload, headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", f"mock-{self.server.request_count}")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Timeout/cancellation conformance checks deliberately close the
            # client socket before a delayed fixture responds. That is an
            # expected transport outcome, not a server failure worth a noisy
            # socketserver traceback.
            return

    @staticmethod
    def _prompt(payload):
        return "\n".join(str(message.get("content", "")) for message in payload.get("messages", []))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.server.request_count += 1
        self.server.last_payloads.append((self.path, payload))
        prompt = self._prompt(payload)
        key = (self.path, prompt)
        self.server.scenario_counts[key] = self.server.scenario_counts.get(key, 0) + 1
        if "[retry-once]" in prompt and self.server.scenario_counts[key] == 1:
            self._json(429, {"error": {"message": "mock rate limit"}}, {"Retry-After": "0"})
            return
        if "[timeout]" in prompt:
            time.sleep(self.server.timeout_delay)
        if self.path.endswith("/v1/messages"):
            self._anthropic(payload)
        else:
            self._openai(payload, prompt)

    def _sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("x-request-id", f"mock-{self.server.request_count}")
        self.end_headers()

    def _event(self, payload, event_id=None):
        if event_id is not None:
            self.wfile.write(f"id: {event_id}\n".encode())
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def _openai(self, payload, prompt):
        if payload.get("stream"):
            self._sse_headers()
            self._event({"model": payload.get("model"), "choices": [{"delta": {"reasoning_content": "mock reasoning"}}]}, 1)
            if payload.get("tools"):
                self._event({"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "id": "call_probe", "type": "function",
                    "function": {"name": "ego_probe_echo", "arguments": "{\"value\":"},
                }]}}]}, 2)
                arguments = "not-json" if "[malformed-tool]" in prompt else "\"ok\"}"
                self._event({"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": arguments},
                }]}}]}, 3)
            else:
                self._event({"choices": [{"delta": {"content": "stream-ok"}}]}, 2)
            self._event({
                "choices": [],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 3}},
            }, 4)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        if payload.get("tools"):
            arguments = "not-json" if "[malformed-tool]" in prompt else json.dumps({"value": "ok"})
            message = {"role": "assistant", "content": None, "reasoning_content": "mock reasoning", "tool_calls": [{
                "id": "call_probe", "type": "function",
                "function": {"name": "ego_probe_echo", "arguments": arguments},
            }]}
            if "[multi-tool]" in prompt:
                message["tool_calls"].append({
                    "id": "call_probe_2", "type": "function",
                    "function": {"name": "ego_probe_echo", "arguments": json.dumps({"value": "two"})},
                })
        elif payload.get("response_format"):
            message = {"role": "assistant", "content": json.dumps({"ok": True, "completion": "mock completion"})}
        else:
            message = {"role": "assistant", "content": "ego-probe-ok", "reasoning_content": "mock reasoning"}
        self._json(200, {
            "id": "mock-completion", "model": payload.get("model", "mock-model"),
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 3}},
        })

    def _anthropic(self, payload):
        prompt = self._prompt(payload)
        if payload.get("stream"):
            self._sse_headers()
            self._event({"type": "message_start", "message": {"model": payload.get("model"), "usage": {"input_tokens": 5}}})
            self._event({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            self._event({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "mock reasoning"}})
            self._event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "stream-ok"}})
            self._event({"type": "message_delta", "usage": {"output_tokens": 2, "cache_read_input_tokens": 3}})
            return
        content = [{"type": "thinking", "thinking": "mock reasoning"}]
        if payload.get("tools"):
            content.append({"type": "tool_use", "id": "call_probe", "name": "ego_probe_echo", "input": {"value": "ok"}})
            stop_reason = "tool_use"
        else:
            text = json.dumps({"ok": True}) if "Return JSON only" in prompt else "ego-probe-ok"
            content.append({"type": "text", "text": text})
            stop_reason = "end_turn"
        self._json(200, {
            "id": "msg_mock", "model": payload.get("model", "mock-anthropic"),
            "content": content, "stop_reason": stop_reason,
            "usage": {"input_tokens": 5, "output_tokens": 2, "cache_read_input_tokens": 3},
        })


class ProviderConformanceServer:
    def __init__(self, timeout_delay=0.2):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.request_count = 0
        self.httpd.scenario_counts = {}
        self.httpd.last_payloads = []
        self.httpd.timeout_delay = float(timeout_delay)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_args):
        self.close()
