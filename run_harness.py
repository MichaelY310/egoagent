"""
启动脚本：加载 harness 并运行
用法: python run_harness.py --harness_dir <dir> --agents slot:identity [slot:identity ...] [--workspace <path>] [--prompts name:value [name:value ...]]
示例: python run_harness.py --harness_dir harness/react_single --agents agent:identity/dante
      python run_harness.py --harness_dir harness/turn_based --agents 正方:identity/id1 反方:identity/id1 裁判:identity/dante --prompts "task:辩题内容"
"""
import argparse
from pathlib import Path

from agent import Agent
from harness import Harness


def main():
    parser = argparse.ArgumentParser(description="启动 harness 并运行 agent 系统")
    parser.add_argument("--harness_dir", type=Path, help="harness 目录路径")
    parser.add_argument("--agents", nargs="+", type=str,
                        help="agent 定义，格式: slot_name:identity_path")
    parser.add_argument("--workspace", type=Path, default=None, help="workspace 目录路径")
    parser.add_argument("--prompts", nargs="+", type=str, default=None,
                        help="prompt 覆盖，格式: name:value（value 中的空格需用引号包裹）")
    args = parser.parse_args()

    # 解析 agents: slot:identity_path 格式
    agents = {}
    for spec in args.agents:
        if ":" in spec:
            slot_name, identity_path = spec.split(":", 1)
        else:
            identity_path = spec
            slot_name = Path(identity_path).name
        agents[slot_name] = Agent(identity_path, name=slot_name)

    # 解析 prompts: name:value 格式
    prompts = None
    if args.prompts:
        prompts = {}
        for spec in args.prompts:
            if ":" in spec:
                name, value = spec.split(":", 1)
                prompts[name] = value
            else:
                print(f"[Warning] 忽略无效 prompt 格式: {spec}（应为 name:value）")

    # 加载 harness 并运行
    harness = Harness(args.harness_dir, agents, workspace=args.workspace, prompts=prompts)
    print(f"[Harness] {harness.name} | slots: {list(agents.keys())}")
    print(f"[Session] -> {harness.session.save_dir}")
    if prompts:
        print(f"[Prompts] {list(prompts.keys())}")
    print()
    harness.run()


if __name__ == "__main__":
    main()
