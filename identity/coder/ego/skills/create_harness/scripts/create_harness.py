"""
创建并运行一个子 harness，将结果注入父 session 的 messages 中。
支持流式可视化：如果存在全局 output 回调，通过 WebSocket 推送子 session 事件。
run() 返回的结果根据 return_mode 决定内容：
  - "all": 子 session 全部消息
  - "last": 只有最后一条非 tool 消息
"""
import uuid
from pathlib import Path


def create_harness(harness_dir: str, agents: str, prompts: str = None, workspace: str = None, inherit_conversation: bool = False, return_mode: str = None):
    from agent import Agent
    from harness import Harness, get_current_harness, get_output_callback
    from pipeline_engine import run_pipeline_stream, run_pipeline

    # 项目根目录（用于将相对路径转为绝对路径）
    PROJECT_ROOT = Path(__file__).resolve().parents[6]

    # 如果没指定 workspace，继承父 harness 的 workspace
    parent_harness = get_current_harness()
    if not workspace and parent_harness and parent_harness.workspace:
        workspace = str(parent_harness.workspace)

    # 解析 agents: "slot:identity_path,slot:identity_path,..."
    agents_dict = {}
    for spec in agents.split(","):
        spec = spec.strip()
        if ":" in spec:
            slot_name, identity_path = spec.split(":", 1)
        else:
            identity_path = spec
            slot_name = Path(identity_path).name
        # 相对路径基于项目根解析
        identity_full = Path(identity_path)
        if not identity_full.is_absolute():
            identity_full = PROJECT_ROOT / identity_path
        agents_dict[slot_name.strip()] = Agent(str(identity_full), name=slot_name.strip())

    # 解析 prompts: "name:value|name:value"
    prompts_dict = None
    if prompts:
        prompts_dict = {}
        if "|" in prompts:
            pairs = prompts.split("|")
        else:
            pairs = [prompts]
        for pair in pairs:
            pair = pair.strip()
            if ":" in pair:
                name, value = pair.split(":", 1)
                prompts_dict[name.strip()] = value.strip()

    # 路径容错：如果 harness_dir 不存在，尝试在项目根和 config 配置下查找
    harness_path = Path(harness_dir)
    if not harness_path.is_absolute():
        harness_path = PROJECT_ROOT / harness_dir
    if not (harness_path / "config.json").exists():
        from config import CONFIG
        repo = Path(CONFIG["harness_template_repository"])
        if not repo.is_absolute():
            repo = PROJECT_ROOT / repo
        fallback = repo / Path(harness_dir).name
        if (fallback / "config.json").exists():
            harness_path = fallback
        else:
            return f"Error: harness_dir '{harness_dir}' not found (also tried '{fallback}')"

    # 创建 harness
    ws = Path(workspace) if workspace else None
    harness = Harness(str(harness_path), agents=agents_dict, workspace=ws, prompts=prompts_dict, return_mode=return_mode)

    # 如果需要继承主 session 的对话历史
    if inherit_conversation:
        parent = get_current_harness()
        if parent and parent.session.messages:
            harness.session.messages = list(parent.session.messages)
            harness.session.full_messages = list(parent.session.full_messages)

    # 获取创建者信息
    creator = "unknown"
    if parent_harness and parent_harness.agents:
        creator_agents = list(parent_harness.agents.values())
        if creator_agents:
            creator = creator_agents[0].name

    slots_info = ", ".join(f"{k}={v.name}" for k, v in harness.agents.items())

    print(f"\n[Sub-Harness] {harness.name} | slots: {list(agents_dict.keys())}")
    print(f"[Sub-Session] -> {harness.session.save_dir}")
    print(f"[Return Mode] {harness.return_mode}")
    if inherit_conversation:
        print(f"[Inherited] {len(harness.session.messages)} messages from parent")
    print()

    # 检查是否有全局 output 回调（流式可视化模式）
    output_cb = get_output_callback()

    if output_cb:
        # 流式模式：通过 WebSocket 推送子 harness 事件
        harness_id = str(uuid.uuid4())[:8]

        # 通知前端：子 harness 开始
        output_cb("sub_harness_start", {
            "harness_id": harness_id,
            "harness_name": harness.name,
            "parent_agent": creator,
            "slots": {k: v.name for k, v in harness.agents.items()},
        })

        def sub_on_output(msg_type, data):
            """子 harness 的 output 回调，转发为 sub_* 事件"""
            if msg_type == "token":
                output_cb("sub_token", {
                    "harness_id": harness_id,
                    "agent": data.get("agent", "unknown"),
                    "text": data.get("text", ""),
                })
            elif msg_type == "tool":
                output_cb("sub_tool", {
                    "harness_id": harness_id,
                    "agent": data.get("agent", "system"),
                    "name": data.get("name", ""),
                    "result": data.get("result", ""),
                })
            elif msg_type == "error":
                output_cb("sub_token", {
                    "harness_id": harness_id,
                    "agent": "system",
                    "text": f"\n❌ {data.get('message', '')}\n",
                })
            # 其他事件（label, node_enter, done 等）不转发

        def sub_get_input():
            # 子 harness 通常不等待用户输入，返回 None 会终止等待
            return None

        def sub_is_running():
            # 检查父 harness 是否仍在运行
            parent_cb = get_output_callback()
            return parent_cb is not None

        # 使用流式引擎运行子 harness
        from harness import set_current_harness, EndSession
        parent = get_current_harness()
        if parent:
            harness.parent = parent
            parent.children.append(harness)
        set_current_harness(harness)

        try:
            run_pipeline_stream(harness, sub_on_output, sub_get_input, sub_is_running)
        except EndSession as e:
            if str(e):
                print(f"\n[Sub-EndSession] {e}")
        finally:
            harness.session.save()
            set_current_harness(parent)

        # 通知前端：子 harness 结束
        output_cb("sub_harness_end", {
            "harness_id": harness_id,
            "harness_name": harness.name,
        })

        result_messages = harness.session.get_result(harness.return_mode)
    else:
        # 非流式模式：直接用 run()
        result_messages = harness.run()

    # 格式化结果返回给调用者（作为 tool result 字符串）
    if not result_messages:
        return f"Harness '{harness.name}' completed. (no messages)"

    summary_parts = [
        f"[Sub-Harness Session 已结束]",
        f"创建者: {creator}",
        f"模板: {harness.name}",
        f"参与者: {slots_info}",
        f"Workspace: {harness.workspace or 'None'}",
        f"Return mode: {harness.return_mode}",
        f"---",
    ]
    for msg in result_messages:
        role = msg.get("role", "unknown")
        name = msg.get("name", role)
        content = msg.get("content", "")
        # all 模式可能很长，截断每条到 500 字
        if len(content) > 500:
            content = content[:500] + "..."
        summary_parts.append(f"[{name}] {content}")

    summary_parts.append(f"---")
    summary_parts.append(f"以上是子 session 的全部内容。子 session 已结束，根据以上内容继续之前的任务。")
    return "\n".join(summary_parts)
