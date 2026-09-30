import json
import os
import re
import time
import hashlib
import requests
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlsplit

from .app_dns_proxy import (
    app_dns_proxy_for_url,
    ensure_app_dns_proxy,
    is_recoverable_direct_connection_error,
)

# class LLM:
#     def __init__(self, config: Dict):

#     def chat()

class CustomLLM:
    def __init__(self, config: Dict):
        self.config = dict(config)

        # A process-level override lets every Identity use one provider without
        # copying a secret into dozens of id.json files. Provider-specific keys
        # are convenient fallbacks when the generic override is absent.
        siliconflow_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        configured_key_env = str(config.get("api_key_env", "")).strip()
        configured_env_key = os.environ.get(configured_key_env, "").strip() if configured_key_env else ""
        global_key = os.environ.get("EGOAGENT_LLM_API_KEY", "").strip()

        default_base_url = (
            "https://api.deepseek.com" if deepseek_key
            else "https://api.siliconflow.cn/v1" if siliconflow_key
            else ""
        )
        default_model = (
            "deepseek-v4-flash" if deepseek_key
            else "Qwen/Qwen3-8B" if siliconflow_key
            else ""
        )
        # A routed profile is already the router's final, audited choice.  Do
        # not silently replace it with a process-wide endpoint after routing;
        # that made telemetry name a mock/local profile while money was spent
        # on a different remote provider. Legacy direct Identity configs still
        # support the original process-level override behavior.
        routed = isinstance(config.get("selection"), dict)
        configured_base = str(config.get("base_url", "")).strip()
        configured_model = str(config.get("model", "")).strip()
        configured_secret = str(config.get("api_key", "")).strip()
        if routed:
            self.base_url = (configured_base or os.environ.get("EGOAGENT_LLM_BASE_URL", "").strip() or default_base_url).rstrip("/")
            self.model = configured_model or os.environ.get("EGOAGENT_LLM_MODEL", "").strip() or default_model
            self.api_key = configured_secret or configured_env_key or global_key or deepseek_key or siliconflow_key
        else:
            self.base_url = (os.environ.get("EGOAGENT_LLM_BASE_URL", "").strip() or default_base_url or configured_base).rstrip("/")
            self.model = os.environ.get("EGOAGENT_LLM_MODEL", "").strip() or default_model or configured_model
            self.api_key = global_key or configured_env_key or deepseek_key or siliconflow_key or configured_secret

        if not self.base_url:
            raise ValueError("LLM base_url is not configured")
        if not self.model:
            raise ValueError("LLM model is not configured")

        self.max_tokens = self._env_number("EGOAGENT_LLM_MAX_TOKENS", config.get("max_tokens"), int)
        self.temperature = self._env_number("EGOAGENT_LLM_TEMPERATURE", config.get("temperature"), float)
        self.timeout = self._env_number("EGOAGENT_LLM_TIMEOUT", config.get("timeout", 120), float) or 120
        self.max_retries = max(0, int(self._env_number("EGOAGENT_LLM_MAX_RETRIES", config.get("max_retries", 2), int) or 0))
        self.retry_backoff = max(0.0, float(self._env_number("EGOAGENT_LLM_RETRY_BACKOFF", config.get("retry_backoff", 0.5), float) or 0))
        self.max_retry_delay = max(0.0, float(config.get("max_retry_delay", 30)))
        retry_statuses = config.get("retry_statuses", [408, 409, 425, 429, 500, 502, 503, 504])
        self.retry_statuses = {int(status) for status in retry_statuses}
        self.stream_resume = self._env_bool("EGOAGENT_LLM_STREAM_RESUME", config.get("stream_resume", True))
        self.last_response_metadata: Dict[str, Any] = {}
        self.last_request_metadata: Dict[str, Any] = {}
        self._request_sequence = 0
        # This is an application-scoped HTTPS tunnel, not a process/system
        # proxy. Only provider calls made by this CustomLLM receive it.
        self.https_proxy = app_dns_proxy_for_url(self.base_url)
        self._dns_fallback_activated = bool(self.https_proxy)

        thinking_env = os.environ.get("EGOAGENT_LLM_ENABLE_THINKING")
        if thinking_env is not None:
            self.enable_thinking = thinking_env.strip().lower() in {"1", "true", "yes", "on"}
        elif "enable_thinking" in config:
            self.enable_thinking = bool(config.get("enable_thinking"))
        elif "deepseek.com" in self.base_url.lower():
            # Identity files created before model profiles do not carry an
            # ``enable_thinking`` field.  Environment overrides can still
            # route those Identities to DeepSeek V4, where omitting ``thinking``
            # enables hidden reasoning by default.  Short interactive/DAG
            # budgets can then be consumed entirely by reasoning and yield an
            # apparently successful but empty response.  Keep the legacy path
            # predictable; users can explicitly opt in through either the
            # Identity config or EGOAGENT_LLM_ENABLE_THINKING.
            self.enable_thinking = False
        elif self.model.startswith("Qwen/Qwen3"):
            # Code agents benefit from lower latency and cleaner tool-call JSON.
            self.enable_thinking = False
        else:
            self.enable_thinking = None

    @staticmethod
    def _env_number(name, fallback, caster):
        value = os.environ.get(name)
        if value is None or value == "":
            return fallback
        try:
            return caster(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _env_bool(name, fallback=False):
        value = os.environ.get(name)
        if value is None:
            return bool(fallback)
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _build_payload(
        self,
        messages,
        tools=None,
        tool_choice=None,
        max_tokens=None,
        temperature=None,
        stream=False,
        response_format=None,
        extra_body=None,
    ):
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if stream:
            payload["stream"] = True
        _max = self.max_tokens if max_tokens is None else max_tokens
        _temp = self.temperature if temperature is None else temperature
        if _max is not None:
            payload["max_tokens"] = int(_max)
        if _temp is not None:
            payload["temperature"] = float(_temp)
        if self.enable_thinking is not None:
            if "deepseek.com" in self.base_url.lower():
                # DeepSeek uses the OpenAI-compatible top-level `thinking`
                # extension. DeepSeek V4 defaults to thinking when this field
                # is omitted, including tool-bearing turns. Always send the
                # explicit disabled value for normal mode; otherwise a small
                # tool loop can spend its entire budget on hidden reasoning.
                # Thinking-enabled tool use remains omitted because compatible
                # endpoints may reject that combination.
                if not self.enable_thinking or not tools:
                    payload["thinking"] = {"type": "enabled" if self.enable_thinking else "disabled"}
            else:
                payload["enable_thinking"] = self.enable_thinking
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)
        return payload

    @staticmethod
    def _merge_tool_call_delta(buffer, tool_call):
        index = int(tool_call.get("index", len(buffer)))
        current = buffer.setdefault(index, {
            "id": "",
            "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if tool_call.get("id"):
            current["id"] = tool_call["id"]
        if tool_call.get("type"):
            current["type"] = tool_call["type"]
        function = tool_call.get("function") or {}
        if function.get("name"):
            name = str(function["name"])
            if not current["function"]["name"].endswith(name):
                current["function"]["name"] += name
        if function.get("arguments") is not None:
            arguments = function["arguments"]
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            current["function"]["arguments"] += arguments

    @staticmethod
    def _tool_calls_from_buffer(buffer):
        calls = []
        for index in sorted(buffer):
            call = buffer[index]
            if not call.get("id"):
                call["id"] = f"call_{index}"
            calls.append(call)
        return calls

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _capture_request_metadata(self, url, payload, *, stream=False):
        """Record the exact provider envelope without secrets or duplicate bodies."""
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        messages = payload.get("messages") or []
        tools = payload.get("tools") or []
        parameters = {
            key: value for key, value in payload.items()
            if key not in {"messages", "tools"}
        }
        self.last_request_metadata = {
            "url": str(url),
            "model": str(payload.get("model") or self.model),
            "stream": bool(stream),
            "parameters": parameters,
            "messages_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
            "tools_sha256": hashlib.sha256(json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        }

    @staticmethod
    def _raise_for_status(resp):
        try:
            resp.raise_for_status()
        except requests.HTTPError as error:
            detail = (resp.text or "").strip().replace("\n", " ")[:600]
            if detail:
                raise requests.HTTPError(f"{error}; provider response: {detail}", response=resp) from error
            raise

    def _retry_delay(self, response, attempt):
        retry_after = (getattr(response, "headers", {}) or {}).get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return min(self.max_retry_delay, max(0.0, float(retry_after)))
            except (TypeError, ValueError):
                try:
                    parsed = parsedate_to_datetime(str(retry_after))
                    return min(self.max_retry_delay, max(0.0, parsed.timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(self.max_retry_delay, self.retry_backoff * (2 ** max(0, attempt - 1)))

    def _post_with_retry(self, url, payload, *, stream=False, headers=None):
        request_headers = dict(headers or self._headers())
        last_error = None
        attempt = 0
        max_attempts = self.max_retries + 1
        while attempt < max_attempts:
            attempt += 1
            response = None
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=request_headers,
                    timeout=self.timeout,
                    stream=stream,
                    proxies={"https": self.https_proxy} if self.https_proxy else None,
                )
                status = int(getattr(response, "status_code", 200))
                if status not in self.retry_statuses or attempt > self.max_retries:
                    self._raise_for_status(response)
                    return response, attempt
                last_error = requests.HTTPError(
                    f"retryable provider status {status}", response=response
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if is_recoverable_direct_connection_error(error) and not self._dns_fallback_activated:
                    hostname = urlsplit(url).hostname
                    if hostname:
                        self.https_proxy = ensure_app_dns_proxy(hostname)
                        self._dns_fallback_activated = True
                        max_attempts += 1
                        continue
                if attempt >= max_attempts:
                    raise
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            delay = self._retry_delay(response, attempt)
            if delay:
                time.sleep(delay)
        raise last_error or requests.RequestException("provider request failed")

    @staticmethod
    def _request_id(response, result=None):
        headers = getattr(response, "headers", {}) or {}
        for name in ("x-request-id", "request-id", "x-amzn-requestid", "cf-ray"):
            if headers.get(name):
                return str(headers[name])
            title_name = "-".join(part.title() for part in name.split("-"))
            if headers.get(title_name):
                return str(headers[title_name])
        if isinstance(result, dict) and result.get("id"):
            return str(result["id"])
        return None

    def _capture_metadata(self, response, *, result=None, attempts=1, stream=False, reconnects=0, request_ids=None):
        self._request_sequence += 1
        usage = result.get("usage") if isinstance(result, dict) else None
        finish_reason = result.get("finish_reason") if isinstance(result, dict) else None
        if finish_reason is None and isinstance(result, dict) and result.get("choices"):
            first_choice = result["choices"][0]
            if isinstance(first_choice, dict):
                finish_reason = first_choice.get("finish_reason")
        finish_reason = str(finish_reason) if finish_reason is not None else None
        request_id = self._request_id(response, result)
        ids = [str(value) for value in (request_ids or []) if value]
        if request_id and request_id not in ids:
            ids.append(request_id)
        self.last_response_metadata = {
            "sequence": self._request_sequence,
            "model": (result or {}).get("model", self.model) if isinstance(result, dict) else self.model,
            "provider_request_id": request_id,
            "provider_request_ids": ids,
            "request": dict(self.last_request_metadata),
            "status_code": int(getattr(response, "status_code", 0) or 0),
            "attempts": int(attempts),
            "retries": max(0, int(attempts) - 1 - int(reconnects)),
            "reconnects": int(reconnects),
            "stream": bool(stream),
            "usage": usage if isinstance(usage, dict) else {},
            "finish_reason": finish_reason,
            "output_truncated": finish_reason in {"length", "max_tokens", "max_output_tokens"},
        }

    @staticmethod
    def _iter_sse_events(response):
        event_id = None
        data_lines = []
        for raw_line in response.iter_lines(decode_unicode=True):
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line or "")
            if line == "":
                if data_lines:
                    yield event_id, "\n".join(data_lines)
                event_id = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "id":
                event_id = value
            elif field == "data":
                data_lines.append(value)
        if data_lines:
            yield event_id, "\n".join(data_lines)

    def _log_to_session(self, direction, messages=None, tools=None, response=None, tool_calls=None):
        """如果有全局 harness，将 LLM 原始 IO 追加写入 llm_io.jsonl"""
        import os
        from harness import get_current_harness
        harness = get_current_harness()
        if not harness or not harness.session.save_dir:
            return
        session = harness.session
        os.makedirs(session.save_dir, exist_ok=True)
        log_entry = {
            "type": f"llm_{direction}",
            "model": self.model,
        }
        if direction == "input":
            log_entry["messages"] = messages
            log_entry["tools"] = tools
        else:
            log_entry["response"] = response
            log_entry["tool_calls"] = tool_calls
        with open(Path(session.save_dir) / "llm_io.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _recover_text_tool_call(message: Dict[str, Any], tools: Optional[List[Dict[str, Any]]]):
        """Recover one explicit, well-formed tool intent from local-model text.

        Some OpenAI-compatible local servers expose tools to the chat template,
        but older open-weight models still emit the intended call as one JSON
        object in a fenced block.  Treating arbitrary prose as executable would
        be unsafe, so this opt-in compatibility path accepts exactly one JSON
        object, requires the canonical ``name``/``arguments`` shape, and checks
        the name against the tools supplied in the same request.
        """
        if not tools or message.get("tool_calls"):
            return None
        content = str(message.get("content") or "")
        candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE)
        if not candidates:
            stripped = content.strip()
            candidates = [stripped] if stripped.startswith("{") and stripped.endswith("}") else []
        if len(candidates) != 1:
            return None
        try:
            value = json.loads(candidates[0])
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or set(value) - {"name", "arguments"}:
            return None
        name = value.get("name")
        arguments = value.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, (dict, str)):
            return None
        allowed = {
            str((tool.get("function") or {}).get("name", ""))
            for tool in tools
            if isinstance(tool, dict) and tool.get("type") == "function"
        }
        if name not in allowed:
            return None
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None
            if not isinstance(parsed_arguments, dict):
                return None
            arguments = parsed_arguments
        canonical = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        call_id = "call_text_" + hashlib.sha256(
            f"{name}\0{canonical}".encode("utf-8")
        ).hexdigest()[:16]
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": canonical},
        }

    def _normalize_text_tool_call(self, result: Dict[str, Any], tools: Optional[List[Dict[str, Any]]]):
        if not self._env_bool("EGOAGENT_LLM_TEXT_TOOL_FALLBACK", False):
            return False
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0].get("message"), dict):
            return False
        recovered = self._recover_text_tool_call(choices[0]["message"], tools)
        if not recovered:
            return False
        choices[0]["message"]["tool_calls"] = [recovered]
        choices[0]["finish_reason"] = "tool_calls"
        self.last_response_metadata["text_tool_fallback"] = True
        return True

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = None,
        max_tokens: int = None,
        temperature: float = None,
        response_format: Optional[Dict[str, Any]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            extra_body=extra_body,
        )
        self._capture_request_metadata(url, payload, stream=False)

        self._log_to_session("input", messages=messages, tools=tools)
        resp, attempts = self._post_with_retry(url, payload)
        result = resp.json()
        if not result.get("choices"):
            raise ValueError("LLM response does not contain choices")
        self._capture_metadata(resp, result=result, attempts=attempts)
        self._normalize_text_tool_call(result, tools)
        self.last_response_metadata["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._log_to_session("output",
                             response=result["choices"][0]["message"].get("content", ""),
                             tool_calls=result["choices"][0]["message"].get("tool_calls"))
        return result

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = None,
        max_tokens: int = None,
        temperature: float = None,
        response_format: Optional[Dict[str, Any]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ):
        started = time.perf_counter()
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            response_format=response_format,
            extra_body=extra_body,
        )
        self._capture_request_metadata(url, payload, stream=True)

        self._log_to_session("input", messages=messages, tools=tools)

        response_parts = []
        reasoning_parts = []
        tool_call_buffer = {}
        stream_result = {"model": self.model, "usage": {}}
        seen_event_ids = set()
        last_event_id = None
        request_ids = []
        total_attempts = 0
        reconnects = 0
        emitted_any = False
        last_response = None
        defer_text_tool_fallback = bool(tools) and self._env_bool(
            "EGOAGENT_LLM_TEXT_TOOL_FALLBACK", False
        )

        while True:
            headers = self._headers()
            if last_event_id:
                headers["Last-Event-ID"] = last_event_id
            resp, attempts = self._post_with_retry(url, payload, stream=True, headers=headers)
            last_response = resp
            total_attempts += attempts
            response_request_id = self._request_id(resp)
            if response_request_id and response_request_id not in request_ids:
                request_ids.append(response_request_id)
            try:
                with resp:
                    # Server-Sent Events are UTF-8 by specification. Some
                    # compatible providers omit charset and otherwise corrupt
                    # Chinese between multi-Agent turns.
                    resp.encoding = "utf-8"
                    for event_id, data in self._iter_sse_events(resp):
                        if event_id and event_id in seen_event_ids:
                            continue
                        if data.strip() == "[DONE]":
                            if event_id:
                                seen_event_ids.add(event_id)
                                last_event_id = event_id
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if event_id:
                            seen_event_ids.add(event_id)
                            last_event_id = event_id
                        if isinstance(chunk.get("usage"), dict):
                            stream_result["usage"] = chunk["usage"]
                        if chunk.get("model"):
                            stream_result["model"] = chunk["model"]
                        if not chunk.get("choices"):
                            continue
                        choice = chunk["choices"][0]
                        if choice.get("finish_reason") is not None:
                            stream_result["finish_reason"] = choice.get("finish_reason")
                        delta = choice.get("delta") or {}
                        # DeepSeek requires hidden reasoning_content to be
                        # passed back with an assistant tool-call message on
                        # the next round. Yield it as metadata; Agent.step keeps
                        # it out of visible text while preserving the protocol.
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(str(delta["reasoning_content"]))
                        if delta.get("content"):
                            response_parts.append(delta["content"])
                            if defer_text_tool_fallback:
                                # We cannot retract streamed prose after it has
                                # been rendered. Buffer the opt-in compatibility
                                # path until we know whether the complete text is
                                # one strict tool-call object.
                                delta = dict(delta)
                                delta.pop("content", None)
                        if delta.get("tool_calls"):
                            for tool_call in delta["tool_calls"]:
                                self._merge_tool_call_delta(tool_call_buffer, tool_call)
                            # Consumers receive a complete snapshot instead of
                            # fragile fragments, so argument JSON is append-only.
                            delta = dict(delta)
                            delta["tool_calls"] = self._tool_calls_from_buffer(tool_call_buffer)
                        if delta:
                            emitted_any = True
                            yield delta
            except requests.RequestException as error:
                can_resume = self.stream_resume and reconnects < self.max_retries
                if not can_resume:
                    self._capture_metadata(
                        resp,
                        result=stream_result,
                        attempts=total_attempts,
                        stream=True,
                        reconnects=reconnects,
                        request_ids=request_ids,
                    )
                    raise
                if emitted_any and not last_event_id:
                    self._capture_metadata(
                        resp,
                        result=stream_result,
                        attempts=total_attempts,
                        stream=True,
                        reconnects=reconnects,
                        request_ids=request_ids,
                    )
                    raise requests.ConnectionError(
                        "provider stream broke after output but supplied no SSE event id; refusing an unsafe replay"
                    ) from error
                reconnects += 1
                delay = self._retry_delay(resp, reconnects)
                if delay:
                    time.sleep(delay)
                continue
            break
        recovered_text_call = None
        if defer_text_tool_fallback and not tool_call_buffer:
            recovered_text_call = self._recover_text_tool_call(
                {"content": "".join(response_parts)}, tools
            )
            if recovered_text_call:
                stream_result["finish_reason"] = "tool_calls"
                emitted_any = True
                yield {"tool_calls": [recovered_text_call]}
            elif response_parts:
                emitted_any = True
                yield {"content": "".join(response_parts)}
        self._capture_metadata(
            last_response,
            result=stream_result,
            attempts=total_attempts,
            stream=True,
            reconnects=reconnects,
            request_ids=request_ids,
        )
        if recovered_text_call:
            self.last_response_metadata["text_tool_fallback"] = True
        self.last_response_metadata["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._log_to_session(
            "output",
            response="".join(response_parts),
            tool_calls=(
                self._tool_calls_from_buffer(tool_call_buffer)
                if tool_call_buffer
                else [recovered_text_call] if recovered_text_call else None
            ),
        )
