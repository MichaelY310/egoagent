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
  3. 从全局 registry 加载所有已注册的 identity/environment 的 tool/knowledge 并索引到 Meilisearch
  4. 运行 harness
  5. 退出时清空索引并停止 Meilisearch 服务
"""
import argparse
import atexit
import json as _json
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


def _load_registry_resources():
    """从全局 registry 加载所有已注册 identity 和 environment 的 tool/knowledge"""
    from environment import load_tools_from_dir, load_knowledges_from_dir

    all_tools = {}
    all_knowledges = {}

    registry_path = Path.home() / ".egoagent_registry.json"
    if not registry_path.exists():
        return all_tools, all_knowledges

    registry = _json.loads(registry_path.read_text(encoding="utf-8"))

    # 加载所有注册的 identity 的 ego/skills 和 ego/knowledge
    for id_path in registry.get("identities", []):
        id_dir = Path(id_path)
        if not id_dir.is_dir():
            continue
        skills_dir = id_dir / "ego" / "skills"
        knowledge_dir = id_dir / "ego" / "knowledge"
        if skills_dir.is_dir():
            tools = load_tools_from_dir(skills_dir)
            for k, v in tools.items():
                if k not in all_tools:
                    all_tools[k] = v
        if knowledge_dir.is_dir():
            knowledges = load_knowledges_from_dir(knowledge_dir)
            for k, v in knowledges.items():
                if k not in all_knowledges:
                    all_knowledges[k] = v

    # 加载所有注册的 environment 的 tools 和 knowledge
    for env_path in registry.get("environments", []):
        env_dir = Path(env_path)
        if not env_dir.is_dir():
            continue
        tools_dir = env_dir / "tools"
        skills_dir = env_dir / "skills"
        knowledge_dir = env_dir / "knowledge"
        t_dir = tools_dir if tools_dir.is_dir() else (skills_dir if skills_dir.is_dir() else None)
        if t_dir:
            tools = load_tools_from_dir(t_dir)
            for k, v in tools.items():
                if k not in all_tools:
                    all_tools[k] = v
        if knowledge_dir.is_dir():
            knowledges = load_knowledges_from_dir(knowledge_dir)
            for k, v in knowledges.items():
                if k not in all_knowledges:
                    all_knowledges[k] = v

    # 加载 custom_paths
    for custom_path in registry.get("custom_paths", []):
        cp = Path(custom_path)
        if not cp.is_dir():
            continue
        tools = load_tools_from_dir(cp / "tools") if (cp / "tools").is_dir() else {}
        skills = load_tools_from_dir(cp / "skills") if (cp / "skills").is_dir() else {}
        knowledges = load_knowledges_from_dir(cp / "knowledge") if (cp / "knowledge").is_dir() else {}
        for k, v in {**tools, **skills}.items():
            if k not in all_tools:
                all_tools[k] = v
        for k, v in knowledges.items():
            if k not in all_knowledges:
                all_knowledges[k] = v

    id_count = len(registry.get("identities", []))
    env_count = len(registry.get("environments", []))
    print(f"[Registry] 已从 {registry_path} 加载 {id_count} identities, {env_count} environments")

    return all_tools, all_knowledges


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

    # --- 从全局 registry 加载所有资源并索引到 Meilisearch ---
    if _meilisearch_mgr:
        if not _meilisearch_mgr.is_running:
            print(f"[Warning] Meilisearch 进程已退出，跳过索引")
        else:
            # 先收集当前 session 中 agent 自带的
            all_tools = {}
            all_knowledges = {}
            for agent in agents.values():
                all_tools.update(agent.tools)
                all_knowledges.update(agent.knowledges)

            # 再从 registry 加载全局已注册的（不覆盖当前 agent 已有的）
            registry_tools, registry_knowledges = _load_registry_resources()
            for k, v in registry_tools.items():
                if k not in all_tools:
                    all_tools[k] = v
            for k, v in registry_knowledges.items():
                if k not in all_knowledges:
                    all_knowledges[k] = v

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
