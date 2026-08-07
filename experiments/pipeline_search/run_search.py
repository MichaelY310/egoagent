#!/usr/bin/env python3
"""
Pipeline Architecture Search (PAS) — 实验入口脚本。

用法：
    python -m experiments.pipeline_search.run_search \
        --strategy mutation \
        --population-size 10 \
        --generations 5 \
        --seed-harness /path/to/harness \
        --output-dir ./pas_output

    或直接运行：
    python experiments/pipeline_search/run_search.py --strategy mutation
"""

import sys
import os
import argparse
import json
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.pipeline_search.search_engine import PipelineArchitectureSearch
from experiments.pipeline_search.dag_validator import validate_pipeline
from experiments.pipeline_search.search_space import SearchSpace
from experiments.pipeline_search.population import Population


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Architecture Search (PAS) - 自动搜索最优 Agent DAG 拓扑"
    )
    parser.add_argument(
        "--strategy",
        choices=["mutation", "generation", "crossover", "hybrid"],
        default="mutation",
        help="搜索策略 (default: mutation)",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=10,
        help="种群大小 (default: 10)",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=5,
        help="最大代数 (default: 5)",
    )
    parser.add_argument(
        "--seed-harness",
        type=str,
        default="",
        help="种子 harness 模板目录（用于初始化种群）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./pas_output",
        help="输出目录 (default: ./pas_output)",
    )
    parser.add_argument(
        "--eval-tasks",
        type=str,
        nargs="*",
        default=None,
        help="评估任务列表",
    )
    parser.add_argument(
        "--mutation-rate",
        type=float,
        default=0.7,
        help="变异率 (default: 0.7)",
    )
    parser.add_argument(
        "--crossover-rate",
        type=float,
        default=0.3,
        help="交叉率 (default: 0.3)",
    )
    parser.add_argument(
        "--validate-only",
        type=str,
        default="",
        help="仅验证指定 config.json 的合法性",
    )
    parser.add_argument(
        "--export-best",
        type=str,
        default="",
        help="从已有搜索结果中导出最优 pipeline",
    )

    args = parser.parse_args()

    # 仅验证模式
    if args.validate_only:
        config_path = Path(args.validate_only)
        if not config_path.exists():
            print(f"[ERROR] File not found: {config_path}")
            sys.exit(1)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        valid, msg = validate_pipeline(config)
        if valid:
            print(f"[OK] 验证通过: {msg}")
        else:
            print(f"[FAIL] 验证失败: {msg}")
            sys.exit(1)
        return

    # 默认评估任务
    eval_tasks = args.eval_tasks or [
        "用 Python 写一个简单的计算器程序",
        "帮我搜索项目中所有包含 TODO 的文件",
        "解释一下快速排序算法的原理",
        "帮我创建一个新的测试文件并写入测试代码",
        "分析这段代码的时间复杂度",
    ]

    # 确定 harness 目录
    harness_dir = args.seed_harness
    if not harness_dir:
        default_harness = PROJECT_ROOT / "harness"
        if default_harness.exists():
            harness_dir = str(default_harness)

    # 构建搜索配置
    search_config = {
        "search_strategy": args.strategy,
        "population_size": args.population_size,
        "max_generations": args.generations,
        "eval_tasks": eval_tasks,
        "mutation_rate": args.mutation_rate,
        "crossover_rate": args.crossover_rate,
        "harness_dir": harness_dir,
        "output_dir": args.output_dir,
    }

    print("=" * 60)
    print("  Pipeline Architecture Search (PAS)")
    print("=" * 60)
    print(f"  Strategy:        {args.strategy}")
    print(f"  Population:      {args.population_size}")
    print(f"  Generations:     {args.generations}")
    print(f"  Mutation Rate:   {args.mutation_rate}")
    print(f"  Crossover Rate:  {args.crossover_rate}")
    print(f"  Harness Dir:     {harness_dir or '(none)'}")
    print(f"  Output Dir:      {args.output_dir}")
    print(f"  Eval Tasks:      {len(eval_tasks)} tasks")
    print("=" * 60)

    # 运行搜索
    pas = PipelineArchitectureSearch(search_config)
    result = pas.run_search()

    # 导出最优
    if args.export_best:
        pas.export_best(args.export_best)
    else:
        export_dir = Path(args.output_dir) / "best_pipeline"
        pas.export_best(str(export_dir))

    # 打印摘要
    print("\n" + "=" * 60)
    print("  搜索完成!")
    print("=" * 60)
    print(f"  最优适应度: {result['best_fitness']:.4f}")
    if result['best_pipeline']:
        best = result['best_pipeline']
        nodes = best.get('pipeline', {}).get('nodes', {})
        print(f"  最优结构:   {best.get('name', 'unknown')}")
        print(f"  节点数:     {len(nodes)}")
        print(f"  节点类型:   {[n.get('op') for n in nodes.values()]}")
    print(f"  搜索轨迹:   {len(result['search_trace'])} 代")
    print("=" * 60)


if __name__ == "__main__":
    main()
