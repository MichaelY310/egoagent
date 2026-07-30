"""
SWE-bench 评估桥接脚本（完整版）

功能：
1. 从 SWE-bench_Verified 数据集读取 task
2. 为每个 task clone 对应 repo，checkout base_commit
3. 启动 egoagent coder 在 repo workspace 中工作
4. 收集 agent 生成的 patch（git diff）
5. 输出符合 SWE-bench 格式的 predictions.jsonl
6. 断点续传：自动跳过已完成的 instance
7. 支持 DummyLLM 离线测试

用法:
    # 使用真实 LLM
    python swebench_eval/run_agent.py --num_tasks 5

    # 使用 DummyLLM 离线测试
    python swebench_eval/run_agent.py --num_tasks 1 --dummy

    # 指定 instance
    python swebench_eval/run_agent.py --instance_id astropy__astropy-12907 --dummy

    # 批量评估 + 断点续传
    python swebench_eval/run_agent.py --num_tasks 100 --resume
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

EGOAGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(EGOAGENT_ROOT))

DEFAULT_DUMMY_SCRIPT = [
    {
        "response": "Let me search for the relevant file first.",
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "glob_search", "arguments": '{"pattern": "**/*.py"}'}
        }]
    },
    {
        "response": "Let me read the file to understand the code.",
        "tool_calls": [{
            "id": "call_2", "type": "function",
            "function": {"name": "read_file", "arguments": '{"file_path": "setup.py"}'}
        }]
    },
    {
        "response": "I've analyzed the code. The fix is straightforward. Let me apply it.",
        "tool_calls": [{
            "id": "call_3", "type": "function",
            "function": {"name": "patch_file", "arguments": '{"file_path": "setup.py", "old_string": "test", "new_string": "test"}'}
        }]
    },
    {
        "response": "Fix complete. The issue has been resolved.",
        "tool_calls": []
    },
]


def _make_dummy_identity(identity_path, dummy_script=None):
    """创建一个使用 DummyLLM 的临时 identity 配置"""
    import tempfile
    import shutil

    if dummy_script is None:
        dummy_script = DEFAULT_DUMMY_SCRIPT

    src = Path(identity_path)
    tmp = Path(tempfile.mkdtemp(prefix="egoagent_dummy_", dir="/tmp"))
    dst = tmp / src.name
    shutil.copytree(str(src), str(dst), symlinks=True)

    id_json = dst / "id.json"
    cfg = json.loads(id_json.read_text())
    cfg["llm"] = {
        "type": "dummy_llm",
        "mode": "scripted",
        "script": dummy_script,
    }
    id_json.write_text(json.dumps(cfg, indent=4))

    return dst


def clone_and_checkout(repo: str, base_commit: str, work_dir: Path) -> Path:
    """Clone repo 并 checkout 到 base_commit"""
    repo_name = repo.replace("/", "__")
    repo_dir = work_dir / repo_name

    if repo_dir.exists():
        print(f"  [repo] {repo_dir} 已存在，跳过 clone")
    else:
        url = f"https://github.com/{repo}.git"
        print(f"  [repo] Cloning {url} ...")
        proxy = "http://sys-proxy-rd-relay.byted.org:8118"
        clone_env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "HTTP_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
        }
        subprocess.run(
            ["git", "clone", "--quiet", url, str(repo_dir)],
            check=True,
            env=clone_env,
        )

    print(f"  [repo] Checkout {base_commit[:8]}...")
    subprocess.run(
        ["git", "checkout", "-f", base_commit],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clean", "-fdx"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    return repo_dir


def run_agent_on_task(
    instance_id: str,
    problem_statement: str,
    repo_dir: Path,
    timeout: int = 300,
    max_steps: int = 50,
    use_dummy: bool = False,
    dummy_script: list = None,
) -> str:
    """
    启动 egoagent coder 处理一个 SWE-bench task。
    返回 git diff（agent 生成的 patch）。
    """
    from agent import Agent
    from harness import Harness

    env_dir = repo_dir / ".environment"
    env_dir.mkdir(exist_ok=True)

    task_prompt = f"""You are solving a GitHub issue in a code repository.
Your working directory is already set to the repository root. All tool paths are relative to it.

## Issue Description
{problem_statement}

## Instructions
1. Search for relevant files using glob_search or search_files (they search from current directory by default).
2. Read the relevant source files with read_file to understand the implementation.
3. Make minimal, targeted changes using patch_file.
4. Do NOT modify test files.
5. After patching, read the modified file to verify correctness.
6. When done, respond with "Fix complete."

## Tool Usage
- glob_search(pattern="**/separable.py") — find files by name pattern
- search_files(pattern="separability_matrix", path=".") — search file contents with regex
- read_file(file_path="path/to/file.py") — ALWAYS read before patching
- patch_file(file_path, old_string, new_string) — old_string must be copied EXACTLY from read_file output (same indentation, same lines)

## Strategy
- Identify the key function/class mentioned in the issue
- Use glob_search to find the file, then read_file to see the code
- Make the minimal fix, then read_file again to verify
"""

    identity_path = "identity/coder"
    if use_dummy:
        identity_path = _make_dummy_identity("identity/coder", dummy_script)
        print(f"  [dummy] 使用 DummyLLM identity: {identity_path}")

    coder = Agent(identity_path, name="agent")

    harness = Harness(
        str(EGOAGENT_ROOT / "harness" / "coder_react"),
        agents={"agent": coder},
        workspace=repo_dir,
    )

    harness.session.record({"role": "user", "content": task_prompt})
    harness.session.record_full({"role": "user", "content": task_prompt})

    print(f"  [agent] 开始处理 {instance_id}...（超时 {timeout}s, 最大 {max_steps} 步）")

    class TimeoutError(Exception):
        pass

    def _timeout_handler(signum, frame):
        raise TimeoutError("超时")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)

    try:
        from harness import set_current_harness
        set_current_harness(harness)

        step_count = 0
        while step_count < max_steps:
            response, tool_calls = coder.step(harness.session.messages)
            if not tool_calls:
                break
            for tc in tool_calls:
                tool_name = tc['function']['name'].split(':')[-1] if ':' in tc['function']['name'] else tc['function']['name']
                args_str = tc['function']['arguments']
                try:
                    args_obj = json.loads(args_str)
                    args_short = {k: (v[:80] + '...' if isinstance(v, str) and len(v) > 80 else v) for k, v in args_obj.items()}
                except Exception:
                    args_short = args_str[:200]
                print(f"    [{tool_name}] args={json.dumps(args_short, ensure_ascii=False)}")
                result = coder.execute_tool_call(tc)
                result_str = str(result)
                if "error" in result_str.lower():
                    print(f"    [{tool_name}] ERROR: {result_str[:300]}")
                else:
                    print(f"    [{tool_name}] result: {result_str[:150]}")
            step_count += 1

        print(f"  [agent] 完成，共 {step_count} 步")
        set_current_harness(None)
        harness.session.save()
    except TimeoutError:
        print(f"  [agent] 超时（{timeout}s），停止处理")
        set_current_harness(None)
    except Exception as e:
        print(f"  [agent] 错误: {e}")
        import traceback
        traceback.print_exc()
        set_current_harness(None)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    result = subprocess.run(
        ["git", "diff"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    patch = result.stdout
    print(f"  [patch] {len(patch)} bytes")
    return patch


def load_checkpoint(output_path: Path) -> dict:
    """加载断点续传进度"""
    ckpt_path = Path(str(output_path) + ".progress.json")
    if ckpt_path.exists():
        return json.loads(ckpt_path.read_text())
    return {"completed": [], "predictions": []}


def save_checkpoint(output_path: Path, completed: list, predictions: list):
    """保存断点续传进度"""
    ckpt_path = Path(str(output_path) + ".progress.json")
    ckpt_path.write_text(json.dumps({
        "completed": completed,
        "predictions": predictions,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="用 egoagent 跑 SWE-bench 评估")
    parser.add_argument("--num_tasks", type=int, default=1, help="评估多少条 task")
    parser.add_argument("--instance_id", type=str, help="只跑特定的 instance")
    parser.add_argument("--output", type=str, default="swebench_eval/predictions.jsonl", help="输出 predictions 文件路径")
    parser.add_argument("--work_dir", type=str, default="swebench_eval/repos", help="clone repo 的工作目录")
    parser.add_argument("--data_path", type=str, default="SWE-bench_Verified/data/test-00000-of-00001.parquet", help="SWE-bench 数据集路径")
    parser.add_argument("--timeout", type=int, default=300, help="每个 task 的超时时间（秒）")
    parser.add_argument("--max_steps", type=int, default=50, help="每个 task 的最大步数")
    parser.add_argument("--dummy", action="store_true", help="使用 DummyLLM 进行离线测试")
    parser.add_argument("--dummy_script", type=str, default=None, help="DummyLLM 脚本 JSON 文件路径")
    parser.add_argument("--resume", action="store_true", help="启用断点续传（跳过已完成的 instance）")
    parser.add_argument("--no_resume", action="store_true", help="禁用断点续传（从头开始）")
    args = parser.parse_args()

    df = pd.read_parquet(args.data_path)
    print(f"数据集共 {len(df)} 条 task")

    if args.instance_id:
        df = df[df["instance_id"] == args.instance_id]
        if len(df) == 0:
            print(f"Error: instance_id '{args.instance_id}' 不在数据集中")
            return
    else:
        df = df.head(args.num_tasks)

    output_path = Path(args.output)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 断点续传
    use_resume = args.resume and not args.no_resume
    checkpoint = load_checkpoint(output_path) if use_resume else {"completed": [], "predictions": []}
    completed_set = set(checkpoint["completed"])
    predictions = checkpoint["predictions"]

    if completed_set:
        print(f"断点续传: 已完成 {len(completed_set)} 条，跳过")

    # 加载 DummyLLM 脚本
    dummy_script = None
    if args.dummy_script:
        dummy_script = json.loads(Path(args.dummy_script).read_text())

    total = len(df)
    for idx, row in df.iterrows():
        instance_id = row["instance_id"]

        if instance_id in completed_set:
            print(f"\n=== [{idx+1}/{total}] {instance_id} (已跳过) ===")
            continue

        print(f"\n=== [{idx+1}/{total}] {instance_id} ===")
        start_time = time.time()

        try:
            repo_dir = clone_and_checkout(row["repo"], row["base_commit"], work_dir)

            patch = run_agent_on_task(
                instance_id,
                row["problem_statement"],
                repo_dir,
                timeout=args.timeout,
                max_steps=args.max_steps,
                use_dummy=args.dummy,
                dummy_script=dummy_script,
            )

            elapsed = time.time() - start_time
            pred = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": "egoagent",
                "_elapsed_seconds": round(elapsed, 1),
                "_steps": -1,
            }
            predictions.append(pred)
            completed_set.add(instance_id)

            if use_resume:
                save_checkpoint(output_path, list(completed_set), predictions)

        except Exception as e:
            print(f"  [error] {e}")
            import traceback
            traceback.print_exc()
            elapsed = time.time() - start_time
            predictions.append({
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": "egoagent",
                "_elapsed_seconds": round(elapsed, 1),
                "_error": str(e)[:200],
            })
            completed_set.add(instance_id)

            if use_resume:
                save_checkpoint(output_path, list(completed_set), predictions)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")

    # 清理 checkpoint
    ckpt_path = Path(str(output_path) + ".progress.json")
    if ckpt_path.exists():
        ckpt_path.unlink()

    # 统计
    with_patch = sum(1 for p in predictions if p.get("model_patch"))
    total_elapsed = sum(p.get("_elapsed_seconds", 0) for p in predictions)

    print(f"\n{'='*60}")
    print(f"评估完成")
    print(f"  Predictions: {output_path}")
    print(f"  总数: {len(predictions)}")
    print(f"  有 patch: {with_patch}")
    print(f"  无 patch: {len(predictions) - with_patch}")
    print(f"  总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
    print(f"{'='*60}")
    print(f"\n下一步：用 SWE-bench 评估：")
    print(f"  bash swebench_eval/run_eval.sh {output_path}")


if __name__ == "__main__":
    main()
