#!/usr/bin/env python3
"""
Evolution Benchmark Runner — CLI entry point.

Usage:
    python run_benchmark.py --suite coding --n-runs 3 --output-dir ./results
    python run_benchmark.py --ablation --suite coding
    python run_benchmark.py --full
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.evo_benchmark.benchmark import EvoBenchmark


def main():
    parser = argparse.ArgumentParser(
        description="Run Evolution Benchmark — evaluate self-evolution effectiveness"
    )
    parser.add_argument(
        "--suite", type=str, nargs="+",
        default=["coding", "reasoning", "writing", "mixed"],
        help="Task suites to evaluate (default: all)"
    )
    parser.add_argument(
        "--ablation", action="store_true",
        help="Run ablation experiment only"
    )
    parser.add_argument(
        "--transfer", action="store_true",
        help="Run transfer test only"
    )
    parser.add_argument(
        "--stability", action="store_true",
        help="Run stability test only"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Run full benchmark (all tests)"
    )
    parser.add_argument(
        "--n-runs", type=int, default=3,
        help="Number of runs for stability testing (default: 3)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=5,
        help="Max evolution iterations per run (default: 5)"
    )
    parser.add_argument(
        "--output-dir", type=str, default="",
        help="Output directory for results (default: experiments/evo_benchmark/results)"
    )
    parser.add_argument(
        "--configs", type=str, nargs="+",
        default=["full", "no_principles", "no_textgrad", "no_gate", "no_frontier", "random_baseline"],
        help="Ablation configurations to test"
    )

    args = parser.parse_args()

    # Build config
    config = {
        "task_suites": args.suite,
        "ablation_configs": args.configs,
        "n_runs": args.n_runs,
        "max_iterations": args.max_iterations,
    }
    if args.output_dir:
        config["output_dir"] = args.output_dir

    # Initialize benchmark
    benchmark = EvoBenchmark(config)

    # Determine what to run
    if args.full:
        results = benchmark.run_full_benchmark()
    elif args.ablation:
        results = benchmark.run_ablation()
        _save_results(results, benchmark.output_dir, "ablation")
    elif args.transfer:
        results = benchmark.run_transfer_test()
        _save_results(results, benchmark.output_dir, "transfer")
    elif args.stability:
        results = benchmark.run_stability_test(n_runs=args.n_runs)
        _save_results(results, benchmark.output_dir, "stability")
    else:
        # Default: run on specified suites with full config
        results = {}
        full_config = benchmark.ablation_configs.get("full", {})
        for suite in args.suite:
            print(f"\n--- Running suite: {suite} ---")
            results[suite] = benchmark.run_single_evolution(
                config=full_config, task_suite=suite
            )
        _save_results(results, benchmark.output_dir, "suites")

    print("\nBenchmark complete.")


def _save_results(results: dict, output_dir: Path, prefix: str):
    """Save results to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = output_dir / filename
    filepath.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"\nResults saved to: {filepath}")


if __name__ == "__main__":
    main()
