"""
DummyLLM - 离线测试用 LLM 后端

支持两种模式：
1. scripted: 按顺序返回预设的 (response, tool_calls) 序列
2. replay: 从 session 的 llm_io.jsonl 重放历史 LLM 交互

使用方式：
    from llm.dummy_llm import DummyLLM

    # Scripted 模式
    llm = DummyLLM({"type": "dummy_llm", "mode": "scripted", "script": [
        {"response": "Let me search for the file.", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "glob_search", "arguments": '{"pattern": "**/separable.py"}'}}
        ]},
        {"response": "I found the file, let me read it.", "tool_calls": [
            {"id": "2", "type": "function", "function": {"name": "read_file", "arguments": '{"file_path": "astropy/modeling/separable.py"}'}}
        ]},
        {"response": "Fix complete.", "tool_calls": []},
    ]})

    # Replay 模式
    llm = DummyLLM({"type": "dummy_llm", "mode": "replay", "replay_path": "sessions/xxx/llm_io.jsonl"})
"""

import json
from typing import List, Dict, Any, Optional


class DummyLLM:
    def __init__(self, config: Dict):
        self.config = config
        self.model = str(config.get("model") or "dummy")
        self.last_response_metadata = {}
        self.mode = config.get("mode", "scripted")
        self._step_idx = 0
        self._replay_entries = []

        if self.mode == "scripted":
            self._script = config.get("script", [])
        elif self.mode == "replay":
            self._load_replay(config.get("replay_path", ""))

    def _load_replay(self, replay_path: str):
        if not replay_path:
            return
        with open(replay_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._replay_entries.append(json.loads(line))

    def _get_scripted_response(self):
        if self._step_idx < len(self._script):
            entry = self._script[self._step_idx]
            self._step_idx += 1
            return entry.get("response", ""), entry.get("tool_calls", [])
        return "", []

    def _get_replay_response(self):
        while self._step_idx < len(self._replay_entries):
            entry = self._replay_entries[self._step_idx]
            self._step_idx += 1
            if entry.get("type") == "llm_output":
                return entry.get("response", ""), entry.get("tool_calls", [])
        return "", []

    def _log_to_session(self, direction, messages=None, tools=None, response=None, tool_calls=None):
        from harness import get_current_harness
        harness = get_current_harness()
        if not harness or not harness.session.save_dir:
            return
        import os
        os.makedirs(harness.session.save_dir, exist_ok=True)
        log_entry = {
            "type": f"llm_{direction}",
            "model": "dummy",
        }
        if direction == "input":
            log_entry["messages"] = messages
            log_entry["tools"] = tools
        else:
            log_entry["response"] = response
            log_entry["tool_calls"] = tool_calls
        with open(harness.session.save_dir / "llm_io.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ) -> Dict[str, Any]:
        self._log_to_session("input", messages=messages, tools=tools)

        if self.mode == "replay":
            response_text, tool_calls = self._get_replay_response()
        else:
            response_text, tool_calls = self._get_scripted_response()

        message = {"role": "assistant", "content": response_text}
        if tool_calls:
            message["tool_calls"] = tool_calls

        result = {
            "choices": [{"message": message}],
        }

        self._log_to_session("output", response=response_text, tool_calls=tool_calls)
        return result

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ):
        self._log_to_session("input", messages=messages, tools=tools)

        if self.mode == "replay":
            response_text, tool_calls = self._get_replay_response()
        else:
            response_text, tool_calls = self._get_scripted_response()

        if response_text:
            yield {"content": response_text, "tool_calls": None}
        if tool_calls:
            yield {"content": "", "tool_calls": tool_calls}

        self._log_to_session("output", response=response_text, tool_calls=tool_calls)
