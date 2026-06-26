"""
Single Agent ReAct Loop
用户输入 → agent 循环（调 tool 或直接回复）→ 等待下一轮输入
支持用户直接调用工具: \tool_name(arg=value)
EndSession 由 harness.run() 捕获，protocol 不需要处理。
"""


def run(harness):
    from harness import parse_user_tool_call, execute_user_tool_call

    agent = harness.agents["agent"]
    while True:
        user_input = input(">>> ")
        if user_input == "exit":
            break

        # 检查是否是用户直接调用工具
        parsed = parse_user_tool_call(user_input)
        if parsed:
            tool_name, arguments = parsed
            print(f"[user-tool] 调用 {tool_name}({arguments})")
            result = execute_user_tool_call(harness, agent, tool_name, arguments)
            print(f"[user-tool] 结果:\n{result if result else '(empty)'}")
            continue

        harness.session.record({"role": "user", "content": user_input})
        harness.session.record_full({"role": "user", "content": user_input})

        step_count = 0
        while True:
            print(f"=== Step {step_count}")
            response, tool_calls = agent.step(harness.session.messages)

            if tool_calls:
                for tool_call in tool_calls:
                    result = agent.execute_tool_call(tool_call)
                    print(f"[tool] {tool_call['function']['name']} -> {result[:100]}")
            else:
                break
            print(f"=== End of step {step_count}")
            step_count += 1
