"""Small replayable activity projection, independent of model/session history."""
import copy
import time


def update_chat_progress(state, event, data):
    relevant = {"node_enter", "model_request", "reasoning", "token", "tool_start",
                "tool_end", "tool", "checkpoint_progress", "input_required", "done",
                "error", "cancelled", "approval_required", "approval"}
    if event not in relevant:
        return
    previous = state.get("chat_progress") or {}
    # A new turn starts after a completed/waiting turn, not on every node.
    if previous.get("status") in {"completed", "error", "cancelled"} and event == "node_enter":
        previous = {}
    progress = copy.deepcopy(previous)
    progress.setdefault("started_at", time.time())
    progress.setdefault("tools", [])
    progress.setdefault("thinking", [])
    progress["updated_at"] = time.time()
    progress["status"] = "running"
    agent = str(data.get("agent") or "Agent")
    if event == "node_enter":
        progress["title"] = f"正在执行 {data.get('node_id', '')} · {data.get('op', '')}"
    elif event == "model_request":
        progress["title"] = f"{agent} 正在思考 · 等待模型返回"
        progress["model_step"] = int(progress.get("model_step", 0)) + 1
    elif event == "reasoning":
        progress["title"] = f"{agent} 正在思考"
        key = f"{data.get('run_id', '')}:{progress.get('model_step', 0)}:{agent}"
        thinking = progress["thinking"]
        if not thinking or thinking[-1]["id"] != key:
            thinking.append({"id": key, "agent": agent, "text": ""})
        item = thinking[-1]
        text = item["text"] + str(data.get("text") or "")
        item["truncated"] = item.get("truncated", False) or len(text) > 16000
        item["text"] = text[-16000:]
        del thinking[:-6]
    elif event == "token":
        progress["title"] = f"{agent} 正在生成回答"
    elif event in {"tool_start", "tool_end", "tool"}:
        name = str(data.get("name") or "tool")
        key = f"{data.get('run_id', '')}:{data.get('tool_call_id') or name}"
        item = next((item for item in reversed(progress["tools"]) if item["id"] == key), None)
        if item is None:
            item = {"id": key, "name": name, "agent": agent}
            progress["tools"].append(item)
        if "arguments" in data:
            # This is a glanceable status view; the exact arguments remain in
            # tool events/trajectory. Bound it before duplicating in snapshots.
            import json
            arguments = json.dumps(data["arguments"], ensure_ascii=False) if not isinstance(data["arguments"], str) else data["arguments"]
            item["arguments"] = arguments[:4000] + ("…" if len(arguments) > 4000 else "")
        item["status"] = "running" if event == "tool_start" else data.get("status", "error" if item.get("status") == "error" else "completed")
        progress["title"] = f"{agent} {'正在执行' if event == 'tool_start' else '已执行'} {name}"
        del progress["tools"][:-24]
    elif event == "checkpoint_progress":
        progress["title"] = str(data.get("message") or "正在保存检查点")
        progress["notice"] = progress["title"]
    elif event in {"input_required", "done", "error", "cancelled"}:
        progress["status"] = event if event in {"error", "cancelled"} else "completed"
        progress["title"] = str(data.get("message") or {
            "input_required": "本轮完成 · 等待你的下一条消息", "done": "本轮已完成",
            "error": "执行失败 · 请查看错误详情", "cancelled": "运行已停止"}[event])
        for item in progress["tools"]:
            if item.get("status") == "running":
                item["status"] = "interrupted"
    elif event == "approval_required":
        progress["status"] = "waiting"
        progress["title"] = f"等待你的审批 · {data.get('tool', '工具调用')}"
    elif event == "approval":
        progress["title"] = "审批已处理 · 正在继续"
    state["chat_progress"] = progress
