#!/usr/bin/env python3
"""
Self-Evolution Engine — CLI 入口。

用法:
  python -m self_evolution.run_evolution --harness react_single --identity dante --iterations 3
  python self_evolution/run_evolution.py --harness react_single --identity dante

示例:
  # 默认：对 react_single harness + dante identity 运行 5 轮进化
  python self_evolution/run_evolution.py

  # 指定参数
  python self_evolution/run_evolution.py --harness coder_react --identity coder --iterations 10

  # 安静模式
  python self_evolution/run_evolution.py --quiet

  # 仅评估当前性能（不进化）
  python self_evolution/run_evolution.py --evaluate-only

  # 查看原则库
  python self_evolution/run_evolution.py --show-principles

  # 查看进化归档
  python self_evolution/run_evolution.py --show-archive
"""

import sys
import json
import argparse
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(
        description="Self-Evolution Engine for EgoAgent — 自进化引擎 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                                          # 默认进化循环
  %(prog)s --harness coder_react --identity coder   # 指定目标
  %(prog)s --iterations 10                          # 更多迭代
  %(prog)s --evaluate-only                          # 仅评估
  %(prog)s --show-principles                        # 查看原则库
  %(prog)s --show-archive                           # 查看归档
        """
    )

    # 主要参数
    parser.add_argument("--harness", default="react_single",
                        help="目标 harness 名称 (default: react_single)")
    parser.add_argument("--identity", default="dante",
                        help="目标 identity 名称 (default: dante)")
    parser.add_argument("--iterations", type=int, default=5,
                        help="最大进化迭代次数 (default: 5)")
    parser.add_argument("--quiet", action="store_true",
                        help="抑制详细输出")

    # 功能模式
    parser.add_argument("--evaluate-only", action="store_true",
                        help="仅评估当前性能，不执行进化")
    parser.add_argument("--show-principles", action="store_true",
                        help="显示当前原则库")
    parser.add_argument("--show-archive", action="store_true",
                        help="显示进化归档历史")
    parser.add_argument("--show-tasks", action="store_true",
                        help="显示任务池")
    parser.add_argument("--generate-tasks", action="store_true",
                        help="生成新的任务池")
    parser.add_argument("--reset-data", action="store_true",
                        help="重置所有进化数据（原则、归档、任务池）")

    args = parser.parse_args()

    from self_evolution.engine import (
        run_evolution_cycle,
        evaluate,
        get_task_pool,
        generate_frontier_tasks,
        _generate_candidate_tasks,
        _load_json,
        _save_json,
        PRINCIPLES_FILE,
        ARCHIVE_FILE,
        TASK_POOL_FILE,
        DATA_DIR,
    )

    # 模式分支
    if args.show_principles:
        principles = _load_json(PRINCIPLES_FILE)
        if not principles:
            print("原则库为空。运行进化循环后将自动积累原则。")
        else:
            print(f"\n{'='*60}")
            print(f"  原则库 ({len(principles)} 条)")
            print(f"{'='*60}")
            for p in sorted(principles, key=lambda x: x.get("score", 0), reverse=True):
                marker = "✓" if p.get("type") == "guiding" else "✗"
                print(f"  {marker} [{p['score']:.2f}] {p['description']}")
                print(f"    (used: {p.get('usage_count', 0)}, success: {p.get('success_count', 0)})")
            print()
        return

    if args.show_archive:
        archive = _load_json(ARCHIVE_FILE)
        if not archive:
            print("进化归档为空。运行进化循环后将自动记录。")
        else:
            print(f"\n{'='*60}")
            print(f"  进化归档 ({len(archive)} 条记录)")
            print(f"{'='*60}")
            for r in archive[-20:]:  # 最近20条
                status = "✓" if r.get("accepted") else "✗"
                print(f"  {status} [{r.get('timestamp', '')}] {r.get('target', '')}")
                print(f"    Action: {r.get('action', '')[:80]}")
                print(f"    Score: {r.get('score_before', 0):.2f} → {r.get('score_after', 0):.2f}")
            print()
        return

    if args.show_tasks:
        tasks = get_task_pool()
        if not tasks:
            print("任务池为空。使用 --generate-tasks 生成。")
        else:
            print(f"\n{'='*60}")
            print(f"  任务池 ({len(tasks)} 个任务)")
            print(f"{'='*60}")
            for t in tasks:
                diff = t.get("difficulty", -1)
                diff_str = f"{diff:.2f}" if diff >= 0 else "未评估"
                zone = ""
                if 0.3 <= diff <= 0.8:
                    zone = " [前沿]"
                print(f"  • {t['description'][:70]}")
                print(f"    难度: {diff_str}{zone}")
            print()
        return

    if args.generate_tasks:
        print(f"正在为 {args.harness}/{args.identity} 生成任务...")
        tasks = _generate_candidate_tasks(args.harness, args.identity)
        _save_json(TASK_POOL_FILE, tasks)
        print(f"已生成 {len(tasks)} 个候选任务。")
        for t in tasks:
            print(f"  • {t['description'][:70]}")
        return

    if args.reset_data:
        confirm = input("确认重置所有进化数据？(y/N) ")
        if confirm.lower() == "y":
            _save_json(PRINCIPLES_FILE, [])
            _save_json(ARCHIVE_FILE, [])
            _save_json(TASK_POOL_FILE, [])
            print("已重置所有数据。")
        else:
            print("取消。")
        return

    if args.evaluate_only:
        print(f"正在评估 {args.harness}/{args.identity}...")
        tasks = get_task_pool()
        if not tasks:
            tasks = _generate_candidate_tasks(args.harness, args.identity)
            _save_json(TASK_POOL_FILE, tasks)
        eval_tasks = [t["description"] for t in tasks[:5]]
        score = evaluate(args.harness, args.identity, eval_tasks)
        print(f"\n评估结果: {score:.2f} (基于 {len(eval_tasks)} 个任务)")
        return

    # 默认：运行进化循环
    report = run_evolution_cycle(
        target_harness=args.harness,
        target_identity=args.identity,
        max_iterations=args.iterations,
        verbose=not args.quiet,
    )

    # 输出最终报告
    if args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
