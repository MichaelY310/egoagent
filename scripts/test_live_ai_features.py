"""Live smoke test for every model-backed IDE operation.

The script reads provider credentials from environment variables.  It never
prints or persists an API key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness_editor.ai_service import get_ai_status, run_ai_operation
from llm.custom_llm import CustomLLM


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    status = get_ai_status()
    require(status["configured"], "provider is not configured")
    print(f"STATUS ok provider={status['provider']} model={status['model']}")

    provider_test = run_ai_operation("test", {})
    require(provider_test.get("ok"), "provider health response was not valid")
    print(f"PROVIDER_TEST ok tokens={provider_test.get('usage', {}).get('total_tokens', '?')}")

    completion = run_ai_operation("completion", {
        "prefix": "def add(a: int, b: int) -> int:\n    return",
        "suffix": "\n\nprint(add(2, 3))\n",
        "language": "python",
        "path": "smoke.py",
    })
    require(completion.get("completion"), "completion was empty")
    print(f"COMPLETION ok chars={len(completion['completion'])}")

    inline_edit = run_ai_operation("inline-edit", {
        "code": "def add(a: int, b: int) -> int:\n    return a - b",
        "before": "",
        "after": "print(add(2, 3))",
        "instruction": "修复这个函数，让它正确执行加法，并保留类型标注",
        "language": "python",
        "path": "smoke.py",
    })
    require("+" in inline_edit.get("replacement", ""), "inline edit did not implement addition")
    print(f"INLINE_EDIT ok label={inline_edit.get('label', '')[:60]}")

    multi_edit = run_ai_operation("edit", {
        "code": "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    return a / b\n",
        "instruction": "为两个函数分别增加简短 docstring，并为 divide 增加除零检查",
        "language": "python",
        "path": "smoke.py",
    })
    require(multi_edit.get("changed") and len(multi_edit.get("hunks", [])) >= 1, "multi edit produced no hunks")
    print(f"MULTI_EDIT ok hunks={len(multi_edit['hunks'])}")

    review = run_ai_operation("review", {
        "code": "def unsafe(user_code):\n    api_key = 'hardcoded-secret-123456'\n    return eval(user_code)\n",
        "language": "python",
        "path": "unsafe.py",
    })
    require(review.get("issues"), "review returned no findings for deliberately unsafe code")
    print(f"REVIEW ok issues={len(review['issues'])}")

    commit = run_ai_operation("commit-message", {
        "changes": "modified llm/custom_llm.py\nadded harness_editor/ai_service.py\nmodified void_extension/egoagent-dag-chat/extension-v12.js",
    })
    require(":" in commit.get("message", ""), "commit message was not conventional")
    print(f"COMMIT_MESSAGE ok value={commit['message']}")

    config = {
        "type": "custom_llm",
        "base_url": status["base_url"],
        "model": status["model"],
        "api_key": "",
        "enable_thinking": False,
        "max_tokens": 160,
        "temperature": 0.1,
    }
    client = CustomLLM(config)
    tools = [{
        "type": "function",
        "function": {
            "name": "read_project_file",
            "description": "Read one project file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }]
    streamed_calls = []
    for delta in client.chat_stream(
        [
            {"role": "system", "content": "Always use the supplied tool to read files."},
            {"role": "user", "content": "调用工具读取 README.md。"},
        ],
        tools=tools,
        tool_choice="auto",
    ):
        if delta.get("tool_calls"):
            streamed_calls = delta["tool_calls"]
    require(streamed_calls, "streaming response did not contain a tool call")
    require(streamed_calls[0]["function"]["name"] == "read_project_file", "streaming tool name was corrupted")
    arguments = json.loads(streamed_calls[0]["function"]["arguments"])
    require(arguments.get("path") == "README.md", "streaming tool arguments were corrupted")
    print("STREAMING_TOOL_CALL ok name=read_project_file path=README.md")

    print("ALL_LIVE_AI_FEATURES_OK")


if __name__ == "__main__":
    main()
