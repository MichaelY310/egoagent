"""End-to-end smoke tests through the running localhost proxy and DAG API."""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8880"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def post(path, payload, timeout=180):
    response = requests.post(BASE + path, json=payload, timeout=timeout)
    if not response.ok:
        raise AssertionError(f"{path} returned {response.status_code}: {response.text[:500]}")
    return response.json()


def stream_chat(payload, timeout=240):
    chunks = []
    done = False
    with requests.post(BASE + "/v1/chat/completions", json={**payload, "stream": True}, timeout=timeout, stream=True) as response:
        if not response.ok:
            raise AssertionError(f"stream returned {response.status_code}: {response.text[:500]}")
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[len("data:") :].strip()
            if data == "[DONE]":
                done = True
                break
            event = json.loads(data)
            chunks.append(event.get("choices", [{}])[0].get("delta", {}).get("content", ""))
    return "".join(chunks), done


def main():
    status = requests.get(BASE + "/api/ai/status", timeout=10).json()
    require(status.get("configured") and status.get("provider") == "siliconflow", "proxy does not expose configured provider")
    print(f"HTTP_STATUS ok model={status.get('model')}")

    health = post("/api/ai/test", {})
    require(health.get("ok"), "HTTP AI health operation failed")
    print("HTTP_AI_OPERATION ok")

    single = post("/v1/chat/completions", {
        "model": "egoagent-dag:react_single:dante",
        "harness": "react_single",
        "identity": "dante",
        "messages": [{"role": "user", "content": "不要调用任何工具，只回复 DAG_SINGLE_OK"}],
    })
    single_text = single.get("choices", [{}])[0].get("message", {}).get("content", "")
    require("DAG_SINGLE_OK" in single_text, f"single DAG response was unexpected: {single_text[:200]}")
    print("DAG_SINGLE_NON_STREAM ok")

    streamed, done = stream_chat({
        "model": "egoagent-dag:react_single:dante",
        "harness": "react_single",
        "identity": "dante",
        "messages": [{"role": "user", "content": "只回复 DAG_STREAM_OK"}],
    })
    require(done and "DAG_STREAM_OK" in streamed, f"single DAG stream was unexpected: {streamed[:200]}")
    print("DAG_SINGLE_STREAM ok")

    fixture = (ROOT / "test.txt").resolve()
    tool_result = post("/v1/chat/completions", {
        "model": "egoagent-dag:react_single:dante",
        "harness": "react_single",
        "identity": "dante",
        "messages": [{
            "role": "user",
            "content": f"必须先调用 read_file 工具读取绝对路径 {fixture}，读取成功后只回复 DAG_TOOL_OK",
        }],
    }, timeout=240)
    tool_text = tool_result.get("choices", [{}])[0].get("message", {}).get("content", "")
    require("DAG_TOOL_OK" in tool_text, f"DAG tool loop did not finish correctly: {tool_text[:300]}")
    print("DAG_REAL_TOOL_LOOP ok tool=read_file")

    multi, multi_done = stream_chat({
        "model": "egoagent-dag:creative_roundtable:dante",
        "harness": "creative_roundtable",
        "identity": "dante",
        "messages": [{"role": "user", "content": "用一句话设计一个帮助程序员休息的简单功能，每位 Agent 都要简短。"}],
    }, timeout=300)
    require(multi_done, "multi-agent stream did not terminate with DONE")
    require(multi.count("[AGENT_START:创意家]") >= 2, "creative agent did not run twice")
    require(multi.count("[AGENT_START:批评家]") >= 2, "critic agent did not run twice")
    require("[AGENT_END]" in multi, "multi-agent stream did not contain Agent end markers")
    require(not any(marker in multi for marker in ("Ã", "Â", "â", "ä¸")), "multi-agent SSE content was decoded as Latin-1")
    print("DAG_MULTI_AGENT_STREAM ok turns=4")

    print("ALL_HTTP_DAG_TESTS_OK")


if __name__ == "__main__":
    main()
