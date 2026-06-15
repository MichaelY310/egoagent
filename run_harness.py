"""
启动脚本：加载 harness 并运行，同时管理 Meilisearch 搜索服务

用法: python run_harness.py --harness_dir <dir> --agents slot:identity [slot:identity ...] [--workspace <path>] [--prompts name:value ...]

示例:
  python run_harness.py --harness_dir harness/react_single --agents agent:identity/dante
  python run_harness.py --harness_dir harness/coder_react --agents agent:identity/coder --workspace /home/tiger/project
  python run_harness.py --harness_dir harness/turn_based --agents 正方:identity/id1 反方:identity/id1 裁判:identity/dante --prompts "task:辩题内容"

流程：
  1. 启动 Meilisearch 服务（自动分配端口）
  2. 加载 harness 和 agent
  3. 将所有 tool 和 knowledge 索引到 Meilisearch
  4. 运行 harness
  5. 退出时清空索引并停止 Meilisearch 服务
"""
import argparse
import atexit
from pathlib import Path

from agent import Agent
from harness import Harness
from meilisearch_manager import MeilisearchManager


# 全局 manager 引用，用于 atexit 清理
_meilisearch_mgr = None


def _cleanup():
    """退出时清理 Meilisearch"""
    global _meilisearch_mgr
    if _meilisearch_mgr and _meilisearch_mgr.is_running:
        _meilisearch_mgr.clear()
        _meilisearch_mgr.stop()


def main():
    global _meilisearch_mgr

    parser = argparse.ArgumentParser(description="启动 harness 并运行 agent 系统")
    parser.add_argument("--harness_dir", type=Path, help="harness 目录路径")
    parser.add_argument("--agents", nargs="+", type=str,
                        help="agent 定义，格式: slot_name:identity_path")
    parser.add_argument("--workspace", type=Path, default=None, help="workspace 目录路径")
    parser.add_argument("--prompts", nargs="+", type=str, default=None,
                        help="prompt 覆盖，格式: name:value（value 中的空格需用引号包裹）")
    parser.add_argument("--no-meilisearch", action="store_true",
                        help="不启动 Meilisearch 服务（轻量模式）")
    args = parser.parse_args()

    # --- 启动 Meilisearch ---
    if not args.no_meilisearch:
        print("[启动] 正在启动 Meilisearch 服务...")
        _meilisearch_mgr = MeilisearchManager(port=7700)
        try:
            _meilisearch_mgr.start()
        except (FileNotFoundError, RuntimeError) as e:
            print(f"[Warning] Meilisearch 启动失败: {e}")
            print("[Warning] 将以无搜索模式运行")
            _meilisearch_mgr = None

    # 注册退出清理
    atexit.register(_cleanup)

    # --- 解析 agents ---
    agents = {}
    for spec in args.agents:
        if ":" in spec:
            slot_name, identity_path = spec.split(":", 1)
        else:
            identity_path = spec
            slot_name = Path(identity_path).name
        agents[slot_name] = Agent(identity_path, name=slot_name)

    # --- 解析 prompts ---
    prompts = None
    if args.prompts:
        prompts = {}
        for spec in args.prompts:
            if ":" in spec:
                name, value = spec.split(":", 1)
                prompts[name] = value
            else:
                print(f"[Warning] 忽略无效 prompt 格式: {spec}（应为 name:value）")

    # --- 加载 harness ---
    harness = Harness(args.harness_dir, agents, workspace=args.workspace, prompts=prompts)
    print(f"[Harness] {harness.name} | slots: {list(agents.keys())}")
    print(f"[Session] -> {harness.session.save_dir}")
    if prompts:
        print(f"[Prompts] {list(prompts.keys())}")

    # --- 索引所有 tool 和 knowledge 到 Meilisearch ---
    if _meilisearch_mgr:
        if not _meilisearch_mgr.is_running:
            print(f"[Warning] Meilisearch 进程已退出，跳过索引")
        else:
            all_tools = {}
            all_knowledges = {}
            for agent in agents.values():
                all_tools.update(agent.tools)
                all_knowledges.update(agent.knowledges)
            if all_tools:
                _meilisearch_mgr.index_tools(all_tools)
            if all_knowledges:
                _meilisearch_mgr.index_knowledges(all_knowledges)
            print(f"[Meilisearch] 已索引 {len(all_tools)} tools, {len(all_knowledges)} knowledges")
            print(f"[Meilisearch] 服务地址: {_meilisearch_mgr.url}")

            # 将 manager 引用注入到每个 agent，供搜索 tool 使用
            for agent in agents.values():
                agent.meilisearch = _meilisearch_mgr

    print()

    # --- 运行 ---
    try:
        harness.run()
    except KeyboardInterrupt:
        print("\n[中断] 用户退出")
    finally:
        # atexit 会自动调用 _cleanup，这里也显式调用一下以确保
        _cleanup()


if __name__ == "__main__":
    main()
