"""
创建并运行一个子 harness，将结果注入父 session 的 messages 中。
run() 返回的结果根据 return_mode 决定内容：
  - "all": 子 session 全部消息
  - "last": 只有最后一条非 tool 消息
"""
from pathlib import Path


def create_harness(harness_dir: str, agents: str, prompts: str = None, workspace: str = None, inherit_conversation: bool = False, return_mode: str = None):
    from agent import Agent
    from harness import Harness, get_current_harness

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
        agents_dict[slot_name] = Agent(identity_path, name=slot_name)

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

    # 路径容错：如果 harness_dir 不存在，尝试在 config.yaml 配置的 harness_template_repository 下查找
    harness_path = Path(harness_dir)
    if not (harness_path / "config.json").exists():
        from config import CONFIG
        repo = Path(CONFIG["harness_template_repository"])
        fallback = repo / harness_path.name
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

    print(f"\n[Sub-Harness] {harness.name} | slots: {list(agents_dict.keys())}")
    print(f"[Sub-Session] -> {harness.session.save_dir}")
    print(f"[Return Mode] {harness.return_mode}")
    if inherit_conversation:
        print(f"[Inherited] {len(harness.session.messages)} messages from parent")
    print()

    # run() 返回根据 return_mode 筛选后的 messages 列表
    result_messages = harness.run()

    # 格式化结果返回给调用者（作为 tool result 字符串）
    if not result_messages:
        return f"Harness '{harness.name}' completed. (no messages)"

    # 获取创建者信息
    creator = "unknown"
    if parent_harness and parent_harness.agents:
        creator_agents = list(parent_harness.agents.values())
        if creator_agents:
            creator = creator_agents[0].name

    slots_info = ", ".join(f"{k}={v.name}" for k, v in harness.agents.items())

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
