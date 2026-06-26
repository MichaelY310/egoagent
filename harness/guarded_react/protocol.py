"""
Guarded ReAct Protocol
用户输入 → [worker:推理] → text + tool_calls → [guardian:处理工具] → 系统执行 → (循环)

和 react_single 结构一致，仅在执行 tool_calls 前加一步 guardian.process_tool_calls()。
"""


def run(harness):
    from harness import parse_user_tool_call, execute_user_tool_call

    worker = harness.agents["worker"]
    guardian = harness.agents["guardian"]

    # 从 prompts 获取 guardian 审查用的 prompt 模板
    review_prompt = harness.prompts.get("guardian_review", None)

    while True:
        user_input = input(">>> ")
        if user_input.strip().lower() in ("exit", "quit", "q"):
            break
        if not user_input.strip():
            continue

        # 用户直接调用工具
        parsed = parse_user_tool_call(user_input)
        if parsed:
            tool_name, arguments = parsed
            print(f"[user-tool] 调用 {tool_name}({arguments})")
            result = execute_user_tool_call(harness, worker, tool_name, arguments)
            print(f"[user-tool] 结果:\n{result if result else '(empty)'}")
            continue

        harness.session.record({"role": "user", "content": user_input})
        harness.session.record_full({"role": "user", "content": user_input})

        step_count = 0
        while True:
            print(f"=== Step {step_count}")
            response, tool_calls = worker.step(harness.session.messages)

            if not tool_calls:
                break

            # guardian 审查工具调用
            allowed, blocked = guardian.process_tool_calls(
                tool_calls, harness.session.messages, review_prompt
            )

            # 被拦截的写 blocked message
            for tool_call, reason in blocked:
                blocked_msg = f"[BLOCKED by {guardian.name}] {reason}"
                tool_name = tool_call['function']['name']
                import json as _json
                tool_msg = {
                    "role": "user",
                    "content": f'<tool_response>{{"tool": "{tool_name}", "status": "blocked", "content": {_json.dumps(blocked_msg, ensure_ascii=False)}}}</tool_response>'
                }
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
                print(f"  [blocked] {tool_name} -> {blocked_msg}")

            # 执行通过的
            for tool_call in allowed:
                result = worker.execute_tool_call(tool_call)
                print(f"  [tool] {tool_call['function']['name']} -> {result[:100]}")

            print(f"=== End of step {step_count}")
            step_count += 1
