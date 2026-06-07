"""
根据 identity 路径创建 Agent 并分配到当前 harness 的指定 slot。
"""
import json


def assign_agent(identity_path: str, slot_name: str):
    from agent import Agent
    from harness import get_current_harness

    harness = get_current_harness()
    if not harness:
        return json.dumps({"error": "No active harness. This tool can only be used inside a running harness."})

    # 检查 slot 是否已被占用
    if slot_name in harness.agents:
        return json.dumps({"error": f"Slot '{slot_name}' is already occupied by agent '{harness.agents[slot_name].name}'."})

    # 检查 slot 是否合法（如果 harness 有 slots 定义）
    if harness.slots and slot_name not in harness.slots:
        return json.dumps({
            "error": f"Slot '{slot_name}' does not exist in harness '{harness.name}'.",
            "available_slots": list(harness.slots.keys())
        })

    try:
        agent = Agent(identity_path, name=slot_name)
        harness.assign_agent(slot_name, agent)
        return json.dumps({
            "success": True,
            "message": f"Agent created from '{identity_path}' and assigned to slot '{slot_name}'."
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to create/assign agent: {str(e)}"})
