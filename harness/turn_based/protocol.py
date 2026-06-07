"""
Turn-Based Debate Protocol with Judge
正方/反方轮流辩论，裁判每轮点评，可提前宣判结束。
所有 prompt 通过 harness.prompts 传入（参见 config.json 中的 prompts 定义）。
"""


def agent_speak(agent, harness, max_steps=3):
    """让一个 agent 完成一次 ReAct 发言，返回最终 response"""
    step_count = 0
    response = ""
    while step_count < max_steps:
        response, tool_calls = agent.step(harness.session.messages)
        if tool_calls:
            for tool_call in tool_calls:
                result = agent.execute_tool_call(tool_call)
                print(f"  [{agent.name}:tool] {tool_call['function']['name']} -> {result[:80]}")
            step_count += 1
        else:
            break
    return response


def run(harness):
    agent_pro = harness.agents["正方"]
    agent_con = harness.agents["反方"]
    judge = harness.agents["裁判"]
    max_rounds = 5

    # 从 harness.prompts 读取所有 prompt
    task = harness.prompts.get("task", "请围绕给定议题展开辩论。")
    debater_prompt = harness.prompts.get("debater", "")
    judge_opening = harness.prompts.get("judge_opening", "")
    judge_review = harness.prompts.get("judge_review", "")
    judge_final = harness.prompts.get("judge_final", "")

    # 设置 superego task_prompt
    agent_pro.identity.SEGO[0]["task_prompt"] = f"你是正方辩手，你的对手是「{agent_con.name}」。\n{debater_prompt}"
    agent_con.identity.SEGO[0]["task_prompt"] = f"你是反方辩手，你的对手是「{agent_pro.name}」。\n{debater_prompt}"
    judge.identity.SEGO[0]["task_prompt"] = judge_opening

    # 辩题作为初始 user message
    harness.session.record({"role": "user", "content": task})
    harness.session.record_full({"role": "user", "content": task})

    # === 裁判开场白 ===
    print(f"\n{'='*40}")
    print("裁判开场")
    print(f"{'='*40}")
    agent_speak(judge, harness)

    # === 辩论轮次 ===
    for round_num in range(1, max_rounds + 1):
        # 正方发言
        print(f"\n{'='*40}")
        print(f"第 {round_num} 轮 - 正方")
        print(f"{'='*40}")
        agent_speak(agent_pro, harness)

        # 反方发言
        print(f"\n{'='*40}")
        print(f"第 {round_num} 轮 - 反方")
        print(f"{'='*40}")
        agent_speak(agent_con, harness)

        # 裁判点评
        print(f"\n{'='*40}")
        print(f"第 {round_num} 轮 - 裁判点评")
        print(f"{'='*40}")

        # 最后一轮强制宣判
        if round_num == max_rounds:
            judge.identity.SEGO[0]["task_prompt"] = judge_final
        else:
            judge.identity.SEGO[0]["task_prompt"] = judge_review

        judge_response = agent_speak(judge, harness)

        # 检查裁判是否宣布结果
        if "[DONE]" in judge_response:
            print(f"\n裁判已宣布结果，辩论结束。")
            break

    print(f"\n{'='*40}")
    print("辩论结束。")
