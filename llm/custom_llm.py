import json
import requests
from typing import List, Dict, Any, Optional

# class LLM:
#     def __init__(self, config: Dict):

#     def chat()

class CustomLLM:
    def __init__(self, config: Dict):
        self.config = config
        self.base_url = config["base_url"].rstrip("/")
        self.model = config["model"]
        self.api_key = config["api_key"]

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
        with open(session.save_dir / "llm_io.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
        }
        _max = max_tokens or getattr(self, "max_tokens", None)
        _temp = temperature or getattr(self, "temperature", None)
        if _max is not None:
            payload["max_tokens"] = _max
        if _temp is not None:
            payload["temperature"] = _temp
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._log_to_session("input", messages=messages, tools=tools)
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        result = resp.json()
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
    ):
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        _max = max_tokens or getattr(self, "max_tokens", None)
        _temp = temperature or getattr(self, "temperature", None)
        if _max is not None:
            payload["max_tokens"] = _max
        if _temp is not None:
            payload["temperature"] = _temp
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._log_to_session("input", messages=messages, tools=tools)

        with requests.post(url, json=payload, headers=headers, timeout=120, stream=True) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data.strip() == "[DONE]":
                    return
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"]
                yield delta
