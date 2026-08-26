"""Exercise the exact execution API used by Void's native DAG Chat panel."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8880"
FIXTURE = (ROOT / ".runtime" / f"native_agent_hunks_{uuid.uuid4().hex[:8]}.py").resolve()
ORIGINAL = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def request(method, path, body=None, timeout=30):
    response = requests.request(method, BASE + path, json=body, timeout=timeout)
    if not response.ok:
        raise AssertionError(f"{method} {path} returned {response.status_code}: {response.text[:500]}")
    return response.json()


def state():
    return request("GET", "/api/execution/state")


def stop():
    try:
        request("POST", "/api/execution/stop", {})
    except Exception:
        pass
    deadline = time.time() + 10
    while time.time() < deadline:
        if not state().get("running"):
            return
        time.sleep(0.2)


def wait_for(predicate, timeout, label):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = state()
        if predicate(last):
            return last
        if not last.get("running"):
            errors = [item.get("text", "") for item in last.get("outputs", []) if item.get("agent") == "system"]
            raise AssertionError(f"execution stopped while waiting for {label}: {' '.join(errors)[:600]}")
        time.sleep(0.35)
    raise AssertionError(f"timed out waiting for {label}; last state={last}")


def output_text(value):
    return "\n".join(str(item.get("text") or "") for item in value.get("outputs", []))


def output_tools(value):
    tools = []
    for item in value.get("outputs", []):
        tools.extend(item.get("tools") or [])
    return tools


def start(harness, agents):
    stop()
    request("POST", "/api/execution/start", {"harness": harness, "agents": agents})
    return wait_for(
        lambda current: current.get("running") and current.get("current_node") in {"wait_input", "input_node"},
        20,
        f"{harness} input node",
    )


def test_real_multi_hunk_edit():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    require(not FIXTURE.exists(), f"refusing to overwrite existing fixture: {FIXTURE}")
    FIXTURE.write_text(ORIGINAL, encoding="utf-8")
    start("coder_react", {"agent": "identity/coder"})
    instruction = (
        "必须调用 multi_edit 工具修改这个绝对路径文件："
        f"{FIXTURE}。一次工具调用完成两处替换："
        "把精确字符串 return 1 替换为 return 10，"
        "把精确字符串 return 2 替换为 return 20。"
        "不要调用其他工具；成功后只回复 NATIVE_EDIT_OK。"
    )
    request("POST", "/api/execution/input", {"text": instruction})
    finished = wait_for(
        lambda current: current.get("current_node") == "wait_input"
        and "NATIVE_EDIT_OK" in output_text(current)
        and any(tool.get("name") == "multi_edit" for tool in output_tools(current)),
        240,
        "native multi_edit tool loop",
    )
    require("NATIVE_EDIT_OK" in output_text(finished), "native Agent did not finish after tool execution")
    print("NATIVE_DAG_TOOL_LOOP ok tool=multi_edit")

    matching = [
        change for change in request("GET", "/api/session/changes")
        if Path(change.get("file_path", "")).resolve() == FIXTURE
    ]
    require(len(matching) == 1, f"expected one canonical tracked change, got {len(matching)}")
    change = matching[0]
    require(change.get("status") == "pending", "tracked change is not pending")
    require(len(change.get("hunks", [])) == 2, f"expected two independent hunks, got {len(change.get('hunks', []))}")
    print("CHANGE_TRACKING ok changes=1 hunks=2")

    request("POST", "/api/session/changes/reject", {"index": change["index"], "hunk_id": 0, "reason": "live test"})
    mixed = FIXTURE.read_text(encoding="utf-8")
    require("return 1" in mixed and "return 20" in mixed, "rejecting one hunk did not preserve the other")
    request("POST", "/api/session/changes/undo", {"index": change["index"], "hunk_id": 0})
    require("return 10" in FIXTURE.read_text(encoding="utf-8"), "undoing hunk reject did not restore the agent edit")
    request("POST", "/api/session/changes/reject", {"index": change["index"], "hunk_id": 0, "reason": "live test"})
    request("POST", "/api/session/changes/accept", {"index": change["index"], "hunk_id": 1})
    status = next(item for item in request("GET", "/api/session/changes") if item["index"] == change["index"])
    require(status.get("status") == "partial", "mixed accept/reject state was not marked partial")
    request("POST", "/api/session/changes/undo", {"index": change["index"], "hunk_id": 1})
    require("return 20" in FIXTURE.read_text(encoding="utf-8"), "undoing accept unexpectedly reverted the code edit")
    request("POST", "/api/session/changes/accept", {"index": change["index"], "hunk_id": 1})
    request("POST", "/api/session/changes/reject", {"index": change["index"], "reason": "restore fixture"})
    require(FIXTURE.read_text(encoding="utf-8") == ORIGINAL, "file-level reject did not restore original content")
    print("PER_HUNK_REVIEW ok reject/undo/reject + accept/undo/accept + restore-file")
    stop()


def test_native_multi_agent():
    start("creative_roundtable", {
        "创意家": "identity/creative_brain",
        "批评家": "identity/sharp_critic",
    })
    request("POST", "/api/execution/input", {
        "text": "用一句话设计一个提醒程序员休息的简单功能。每位 Agent 最多两句话。",
    })
    finished = wait_for(
        lambda current: current.get("current_node") == "wait_input"
        and sum(1 for item in current.get("outputs", []) if item.get("agent") in {"创意家", "批评家"}) >= 4,
        300,
        "native four-turn multi-agent DAG",
    )
    agents = [item.get("agent") for item in finished.get("outputs", []) if item.get("agent") in {"创意家", "批评家"}]
    combined = output_text(finished)
    require(agents.count("创意家") >= 2 and agents.count("批评家") >= 2, f"unexpected Agent turns: {agents}")
    require(not any(marker in combined for marker in ("Ã", "Â", "â", "ä¸")), "native multi-Agent text contains mojibake")
    print("NATIVE_MULTI_AGENT ok turns=4 utf8=true")
    stop()


def main():
    try:
        test_real_multi_hunk_edit()
        test_native_multi_agent()
        print("ALL_NATIVE_EXECUTION_TESTS_OK")
    finally:
        stop()
        if FIXTURE.exists():
            FIXTURE.unlink()


if __name__ == "__main__":
    main()
