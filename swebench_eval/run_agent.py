"""
SWE-bench 评估桥接脚本：
1. 从 SWE-bench_Verified 数据集读取 task
2. 为每个 task clone 对应 repo，checkout base_commit
3. 启动 egoagent coder 在 repo workspace 中工作
4. 收集 agent 生成的 patch（git diff）
5. 输出符合 SWE-bench 格式的 predictions.jsonl

用法:
    python swebench_eval/run_agent.py --num_tasks 1
    python swebench_eval/run_agent.py --instance_id astropy__astropy-12907
    python swebench_eval/run_agent.py --num_tasks 5 --output swebench_eval/my_predictions.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

# 添加 egoagent 根目录到 path
EGOAGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(EGOAGENT_ROOT))


def clone_and_checkout(repo: str, base_commit: str, work_dir: Path) -> Path:
    """Clone repo 并 checkout 到 base_commit"""
    repo_name = repo.replace("/", "__")
    repo_dir = work_dir / repo_name

    if repo_dir.exists():
        print(f"  [repo] {repo_dir} 已存在，跳过 clone")
    else:
        url = f"https://github.com/{repo}.git"
        print(f"  [repo] Cloning {url} ...")
        subprocess.run(
            ["git", "clone", "--quiet", url, str(repo_dir)],
            check=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    print(f"  [repo] Checkout {base_commit[:8]}...")
    subprocess.run(
        ["git", "checkout", "-f", base_commit],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    # 清理工作区
    subprocess.run(
        ["git", "clean", "-fdx"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    return repo_dir


def run_agent_on_task(instance_id: str, problem_statement: str, repo_dir: Path) -> str:
    """
    启动 egoagent coder 处理一个 SWE-bench task。
    返回 git diff（agent 生成的 patch）。
    """
    from agent import Agent
    from harness import Harness

    # 在 repo 目录创建 .environment（如果不存在）
    env_dir = repo_dir / ".environment"
    env_dir.mkdir(exist_ok=True)

    # 构建 task prompt
    task_prompt = f"""你正在参与 SWE-bench 评估。你的任务是修复以下 GitHub issue。

## Issue 描述
{problem_statement}

## 要求
1. 先阅读相关代码，理解问题
2. 做出最小化的修改来修复这个 issue
3. 不要修改测试文件
4. 只修改必要的源代码文件
5. 修复完成后，请说"修复完成"

## 当前 repo 路径
{repo_dir}
"""

    # 创建 agent
    coder = Agent("identity/coder", name="agent")

    # 创建 harness
    harness = Harness(
        str(EGOAGENT_ROOT / "harness" / "react_single"),
        agents={"agent": coder},
        workspace=repo_dir,
    )

    # 注入 task 作为 user message
    harness.session.record({"role": "user", "content": task_prompt})
    harness.session.record_full({"role": "user", "content": task_prompt})

    # 运行（非交互模式 - 直接执行 protocol 中的内层循环）
    print(f"  [agent] 开始处理 {instance_id}...")
    try:
        from harness import set_current_harness
        set_current_harness(harness)

        step_count = 0
        max_steps = 30
        while step_count < max_steps:
            response, tool_calls = coder.step(harness.session.messages)
            if not tool_calls:
                break
            for tc in tool_calls:
                result = coder.execute_tool_call(tc)
                print(f"    [tool] {tc['function']['name']} -> {str(result)[:80]}")
            step_count += 1

        set_current_harness(None)
        harness.session.save()
    except Exception as e:
        print(f"  [agent] 错误: {e}")
        set_current_harness(None)

    # 获取 git diff
    result = subprocess.run(
        ["git", "diff"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    patch = result.stdout
    print(f"  [patch] {len(patch)} bytes")
    return patch


def main():
    parser = argparse.ArgumentParser(description="用 egoagent 跑 SWE-bench 评估")
    parser.add_argument("--num_tasks", type=int, default=1, help="评估多少条 task")
    parser.add_argument("--instance_id", type=str, help="只跑特定的 instance")
    parser.add_argument(
        "--output",
        type=str,
        default="swebench_eval/predictions.jsonl",
        help="输出 predictions 文件路径",
    )
    parser.add_argument(
        "--work_dir",
        type=str,
        default="swebench_eval/repos",
        help="clone repo 的工作目录",
    )
    parser.add_argument(
        "--data_path",
        type=str,
        default="SWE-bench_Verified/data/test-00000-of-00001.parquet",
        help="SWE-bench 数据集路径",
    )
    args = parser.parse_args()

    # 加载数据
    df = pd.read_parquet(args.data_path)
    print(f"数据集共 {len(df)} 条 task")

    if args.instance_id:
        df = df[df["instance_id"] == args.instance_id]
        if len(df) == 0:
            print(f"Error: instance_id '{args.instance_id}' 不在数据集中")
            return
    else:
        df = df.head(args.num_tasks)

    print(f"将评估 {len(df)} 条 task")

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    predictions = []
    for idx, row in df.iterrows():
        instance_id = row["instance_id"]
        print(f"\n=== [{idx+1}/{len(df)}] {instance_id} ===")

        try:
            # Clone 并 checkout
            repo_dir = clone_and_checkout(row["repo"], row["base_commit"], work_dir)

            # 运行 agent
            patch = run_agent_on_task(
                instance_id, row["problem_statement"], repo_dir
            )

            pred = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": "egoagent",
            }
            predictions.append(pred)

        except Exception as e:
            print(f"  [error] {e}")
            predictions.append(
                {
                    "instance_id": instance_id,
                    "model_patch": "",
                    "model_name_or_path": "egoagent",
                }
            )

    # 写入 predictions
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")

    print(f"\n=== 完成 ===")
    print(f"Predictions 写入: {output_path}")
    print(f"共 {len(predictions)} 条，其中有 patch 的: {sum(1 for p in predictions if p['model_patch'])}")
    print(f"\n下一步：用 SWE-bench 评估：")
    print(f"  bash swebench_eval/run_eval.sh {output_path}")


if __name__ == "__main__":
    main()
