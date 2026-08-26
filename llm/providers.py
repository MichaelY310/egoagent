"""Provider adapters and capability probing for EgoAgent model roles."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from .custom_llm import CustomLLM


MODEL_ROLES = (
    "chat", "tool_use", "edit", "apply", "autocomplete",
    "embedding", "rerank", "vision", "reasoning",
)


def _provider_kind(config: dict[str, Any]) -> str:
    explicit = str(config.get("provider") or config.get("type") or "").strip().lower().replace("-", "_")
    base_url = str(config.get("base_url") or os.environ.get("EGOAGENT_LLM_BASE_URL", "")).lower()
    if explicit in {"anthropic", "anthropic_compatible"}:
        return "anthropic_compatible"
    if explicit == "ollama" or "11434" in base_url or "ollama" in base_url:
        return "ollama"
    if explicit == "deepseek" or "deepseek" in base_url:
        return "deepseek"
    if explicit == "siliconflow" or "siliconflow" in base_url:
        return "siliconflow"
    return "openai_compatible"


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    kind = _provider_kind(normalized)
    normalized["provider"] = kind
    base_url = str(normalized.get("base_url") or "").rstrip("/")
    if kind == "ollama":
        if not base_url:
            base_url = "http://127.0.0.1:11434/v1"
        elif not base_url.endswith("/v1"):
            base_url += "/v1"
        normalized["base_url"] = base_url
        normalized.setdefault("api_key", "ollama-local")
    return normalized


def create_provider(config: dict[str, Any]):
    """Create an adapter without leaking provider-specific logic to Agents."""
    normalized = _normalize_config(config)
    if normalized["provider"] == "anthropic_compatible":
        return AnthropicCompatibleLLM(normalized)
    return CustomLLM(normalized)


class AnthropicCompatibleLLM(CustomLLM):
    """Translate EgoAgent's OpenAI-shaped contract to Anthropic Messages."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        configured_env = str(config.get("api_key_env") or "ANTHROPIC_API_KEY")
        self.api_key = (
            os.environ.get(configured_env, "").strip()
            or os.environ.get("ANTHROPIC_API_KEY", "").strip()
            or str(config.get("api_key") or "").strip()
        )
        self.anthropic_version = str(config.get("anthropic_version") or "2023-06-01")

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _convert_tools(tools: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools or []:
            function = tool.get("function", tool)
            if not function.get("name"):
                continue
            converted.append({
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function.get("parameters") or function.get("input_schema") or {"type": "object"},
            })
        return converted

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        systems = []
        converted = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content")
            if role == "system":
                if content:
                    systems.append(str(content))
                continue
            if role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": message.get("tool_call_id", ""),
                        "content": str(content or ""),
                    }],
                })
                continue
            if role == "assistant" and message.get("tool_calls"):
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                for call in message.get("tool_calls", []):
                    function = call.get("function", {})
                    arguments = function.get("arguments", "{}")
                    try:
                        value = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except (TypeError, ValueError):
                        value = {"_malformed_arguments": str(arguments)}
                    blocks.append({
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "input": value if isinstance(value, dict) else {"value": value},
                    })
                converted.append({"role": "assistant", "content": blocks})
                continue
            converted.append({"role": "assistant" if role == "assistant" else "user", "content": content or ""})
        return "\n\n".join(systems), converted

    def _payload(self, messages, tools, tool_choice, max_tokens, temperature, stream):
        system, converted_messages = self._convert_messages(messages)
        payload = {
            "model": self.model,
            "messages": converted_messages,
            "max_tokens": int(max_tokens or self.max_tokens or 1024),
            "stream": bool(stream),
        }
        if system:
            payload["system"] = system
        if temperature is not None or self.temperature is not None:
            payload["temperature"] = float(self.temperature if temperature is None else temperature)
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools
            if tool_choice:
                payload["tool_choice"] = {"type": "any"} if tool_choice in {"required", "any"} else tool_choice
        return payload

    @staticmethod
    def _normalize_message(result: dict[str, Any]) -> dict[str, Any]:
        text = []
        reasoning = []
        tool_calls = []
        for block in result.get("content", []) or []:
            block_type = block.get("type")
            if block_type == "text":
                text.append(str(block.get("text", "")))
            elif block_type in {"thinking", "reasoning"}:
                reasoning.append(str(block.get("thinking") or block.get("text") or ""))
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": block.get("id") or f"call_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text) or None}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tool_calls:
            message["tool_calls"] = tool_calls
        usage = result.get("usage") or {}
        return {
            "id": result.get("id"),
            "model": result.get("model"),
            "choices": [{"index": 0, "message": message, "finish_reason": result.get("stop_reason")}],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "prompt_tokens_details": {"cached_tokens": usage.get("cache_read_input_tokens", 0)},
            },
        }

    def chat(self, messages, tools=None, tool_choice=None, max_tokens=None, temperature=None, **_kwargs):
        payload = self._payload(messages, tools, tool_choice, max_tokens, temperature, False)
        self._capture_request_metadata(f"{self.base_url}/v1/messages", payload, stream=False)
        self._log_to_session("input", messages=messages, tools=tools)
        response, attempts = self._post_with_retry(f"{self.base_url}/v1/messages", payload)
        normalized = self._normalize_message(response.json())
        self._capture_metadata(response, result=normalized, attempts=attempts)
        message = normalized["choices"][0]["message"]
        self._log_to_session("output", response=message.get("content"), tool_calls=message.get("tool_calls"))
        return normalized

    def chat_stream(self, messages, tools=None, tool_choice=None, max_tokens=None, temperature=None, **_kwargs):
        payload = self._payload(messages, tools, tool_choice, max_tokens, temperature, True)
        self._capture_request_metadata(f"{self.base_url}/v1/messages", payload, stream=True)
        self._log_to_session("input", messages=messages, tools=tools)
        response, attempts = self._post_with_retry(f"{self.base_url}/v1/messages", payload, stream=True)
        tool_buffers: dict[int, dict[str, Any]] = {}
        result = {"model": self.model, "usage": {}}
        with response:
            response.encoding = "utf-8"
            for _event_id, data in self._iter_sse_events(response):
                try:
                    event = json.loads(data)
                except (TypeError, ValueError):
                    continue
                event_type = event.get("type")
                if event_type == "message_start":
                    message = event.get("message", {})
                    result["model"] = message.get("model", result["model"])
                    result["usage"].update(message.get("usage") or {})
                elif event_type == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        tool_buffers[int(event.get("index", 0))] = {
                            "id": block.get("id", ""), "name": block.get("name", ""), "arguments": ""
                        }
                elif event_type == "content_block_delta":
                    index = int(event.get("index", 0))
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield {"content": delta.get("text", "")}
                    elif delta.get("type") == "thinking_delta":
                        yield {"reasoning_content": delta.get("thinking", "")}
                    elif delta.get("type") == "input_json_delta":
                        current = tool_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        current["arguments"] += str(delta.get("partial_json", ""))
                        yield {"tool_calls": [{
                            "index": item_index,
                            "id": item["id"] or f"call_{item_index}",
                            "type": "function",
                            "function": {"name": item["name"], "arguments": item["arguments"]},
                        } for item_index, item in sorted(tool_buffers.items())]}
                elif event_type == "message_delta":
                    result["usage"].update(event.get("usage") or {})
        normalized_usage = {
            "prompt_tokens": result["usage"].get("input_tokens", 0),
            "completion_tokens": result["usage"].get("output_tokens", 0),
            "prompt_tokens_details": {"cached_tokens": result["usage"].get("cache_read_input_tokens", 0)},
        }
        self._capture_metadata(
            response,
            result={"model": result["model"], "usage": normalized_usage},
            attempts=attempts,
            stream=True,
        )


@dataclass
class ProbeCheck:
    ok: bool
    latency_ms: float
    detail: str = ""


@dataclass
class ModelProbeResult:
    provider: str
    model: str
    healthy: bool
    capabilities: dict[str, bool]
    checks: dict[str, ProbeCheck] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = {name: asdict(check) for name, check in self.checks.items()}
        return data


def probe_model(client, provider: Optional[str] = None) -> ModelProbeResult:
    """Run small real protocol checks and map results to product model roles."""
    kind = provider or getattr(client, "config", {}).get("provider") or _provider_kind(getattr(client, "config", {}))
    checks: dict[str, ProbeCheck] = {}
    capabilities = {role: False for role in MODEL_ROLES}
    usage: dict[str, Any] = {}
    reasoning_seen = False

    def run_check(name, operation):
        started = time.perf_counter()
        try:
            value = operation()
            checks[name] = ProbeCheck(True, round((time.perf_counter() - started) * 1000, 2))
            return value
        except Exception as error:
            checks[name] = ProbeCheck(False, round((time.perf_counter() - started) * 1000, 2), str(error)[:500])
            return None

    text_response = run_check(
        "text",
        lambda: client.chat([{"role": "user", "content": "Reply with exactly: ego-probe-ok"}], max_tokens=128, temperature=0),
    )
    if text_response:
        message = text_response.get("choices", [{}])[0].get("message", {})
        capabilities["chat"] = bool(message.get("content"))
        reasoning_seen = bool(message.get("reasoning_content"))
        usage.update(text_response.get("usage") or {})

    stream_deltas = run_check(
        "stream",
        lambda: list(client.chat_stream([{"role": "user", "content": "Reply with exactly: stream-ok"}], max_tokens=128, temperature=0)),
    )
    if stream_deltas:
        reasoning_seen = reasoning_seen or any(delta.get("reasoning_content") for delta in stream_deltas)

    json_response = run_check(
        "json",
        lambda: client.chat(
            [{"role": "user", "content": 'Return JSON only: {"ok": true}'}],
            max_tokens=128,
            temperature=0,
            response_format={"type": "json_object"},
        ),
    )
    json_ok = False
    if json_response:
        try:
            json_ok = isinstance(json.loads(json_response["choices"][0]["message"].get("content") or ""), dict)
        except (KeyError, TypeError, ValueError):
            json_ok = False

    tools = [{
        "type": "function",
        "function": {
            "name": "ego_probe_echo",
            "description": "Return the supplied value",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }]
    tool_response = run_check(
        "tool_use",
        lambda: client.chat(
            [{"role": "user", "content": "Call ego_probe_echo once with value=ok."}],
            tools=tools,
            # DeepSeek V4 Flash currently rejects explicit tool_choice even
            # when the request omits the thinking extension. A clear prompt
            # still elicits a normal tool call, so leave selection on auto.
            tool_choice=None if str(kind) == "deepseek" else "required",
            max_tokens=256,
            temperature=0,
        ),
    )
    if tool_response:
        capabilities["tool_use"] = bool(
            tool_response.get("choices", [{}])[0].get("message", {}).get("tool_calls")
        )

    capabilities["reasoning"] = reasoning_seen or bool(getattr(client, "enable_thinking", False))
    capabilities["edit"] = capabilities["chat"] and json_ok
    capabilities["apply"] = capabilities["edit"]
    capabilities["autocomplete"] = capabilities["chat"]
    declared = getattr(client, "config", {}).get("capabilities", {})
    if isinstance(declared, dict):
        for role in MODEL_ROLES:
            if role in declared:
                capabilities[role] = bool(declared[role])
    healthy = checks.get("text", ProbeCheck(False, 0)).ok and capabilities["chat"]
    error = None if healthy else next((check.detail for check in checks.values() if not check.ok and check.detail), "Model did not return text")
    return ModelProbeResult(
        provider=str(kind),
        model=str(getattr(client, "model", "")),
        healthy=healthy,
        capabilities=capabilities,
        checks=checks,
        usage=usage,
        error=error,
    )
