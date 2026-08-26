"""
自动化 harness 测试脚本：注入消息后运行 pipeline，捕获完整输出轨迹。
不需要交互，适合用于观察 agent 行为和 prompt 质量。
"""
import sys
import os
import json
from pathlib import Path

os.chdir("/home/tiger/egoagent")
sys.path.insert(0, "/home/tiger/egoagent")

from agent import Agent
from harness import Harness, set_current_harness
from pipeline_engine import run_pipeline


def run_test(task_description: str, harness_name: str = "react_single", identity: str = "identity/dante"):
    """运行一个测试任务，返回 session messages"""
    print(f"\n{'='*80}")
    print(f"TASK: {task_description}")
    print(f"HARNESS: {harness_name} | IDENTITY: {identity}")
    print(f"{'='*80}\n")

    # 创建 agent 和 harness
    agent = Agent(identity, name="agent")
    harness_dir = Path(f"harness/{harness_name}")
    harness = Harness(harness_dir, agents={"agent": agent})

    # 注入用户消息（跳过等待输入节点）
    harness.session.record({"role": "user", "content": task_description})
    harness.session.record_full({"role": "user", "content": task_description})

    # 标记为非交互模式，这样当回到 "等待输入" 时会自动结束
    harness._non_interactive = True

    # 运行
    set_current_harness(harness)
    try:
        run_pipeline(harness)
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
    finally:
        harness.session.save()
        set_current_harness(None)

    print(f"\n{'='*80}")
    print(f"SESSION SAVED: {harness.session.save_dir}")
    print(f"MESSAGES COUNT: {len(harness.session.messages)}")
    print(f"{'='*80}\n")

    # 打印摘要
    for i, msg in enumerate(harness.session.messages):
        role = msg.get("role", "?")
        name = msg.get("name", "")
        content = msg.get("content", "")[:300]
        print(f"  [{i}] {role}{f' ({name})' if name else ''}: {content}")
        print()

    return harness.session.messages


if __name__ == "__main__":
    # Test 1: 简单问答（不需要工具）
    print("\n" + "="*80)
    print("TEST 1: 简单问答 - 验证 system prompt 和基础推理")
    print("="*80)
    run_test("用一句话解释什么是递归")

    print("\n\n")

    # Test 2: 使用工具（读取文件）
    print("="*80)
    print("TEST 2: 工具调用 - 读取文件并总结")
    print("="*80)
    run_test("读取文件 /home/tiger/egoagent/config.yaml 的内容并总结它的作用")

    print("\n\n")

    # Test 3: 列出可用身份（自进化相关）
    print("="*80)
    print("TEST 3: 自进化 - 列出身份")
    print("="*80)
    run_test("列出所有可用的 identity，告诉我每个的作用")
