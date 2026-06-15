"""
Coder ReAct Protocol
用户输入编程任务 → agent 循环（读代码、搜索、编辑、执行命令）→ 给出文本回复 → 等待下一轮输入
增强：
- 更大的 step 上限（30 步）
- 自动注入 workspace 信息
- tool 执行结果预览更长
"""


def run(harness):
    agent = harness.agents["agent"]
    max_steps = 30  # coding 任务允许更多步骤

    # 自动注入 workspace 信息到首条消息
    if harness.workspace:
        workspace_msg = f"[System] Working directory: {harness.workspace}"
        harness.session.record({"role": "system", "content": workspace_msg})
        harness.session.record_full({"role": "system", "content": workspace_msg})

    while True:
        user_input = input(">>> ")
        if user_input.strip().lower() in ("exit", "quit", "q"):
            break
        if not user_input.strip():
            continue

        harness.session.record({"role": "user", "content": user_input})
        harness.session.record_full({"role": "user", "content": user_input})

        step_count = 0
        while step_count < max_steps:
            response, tool_calls = agent.step(harness.session.messages)

            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    result = agent.execute_tool_call(tool_call)
                    # 显示 tool 调用结果预览（coding 场景需要更多上下文）
                    preview = result[:200] if result else "(empty)"
                    print(f"  [{tool_name}] {preview}")
            else:
                # 没有 tool_calls，agent 给出了文本回复，本轮结束
                break

            step_count += 1

        if step_count >= max_steps:
            print(f"[Warning] Reached max steps ({max_steps}), stopping.")
