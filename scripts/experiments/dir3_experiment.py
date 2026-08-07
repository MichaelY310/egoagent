#!/usr/bin/env python3
"""
方向3: Evolution Benchmark（进化基准）实验
跑一轮简化的 benchmark（2个task suite，每个取3题），跑一次进化循环，
收集 EvolutionTrace 并计算24项指标
"""
import sys
import json
import time
import signal
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# Timeout handler
# ============================================================
def timeout_handler(signum, frame):
    raise TimeoutError("Experiment timed out (3500s)")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(3500)

# ============================================================
# 实验主体
# ============================================================
def run_experiment():
    results = {
        "direction": "dir3_evolution_benchmark",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        from experiments.evo_benchmark.benchmark import EvoBenchmark
        from experiments.evo_benchmark.metrics import (
            EvolutionTrace, BenchmarkMetrics, compute_all_metrics,
        )

        # Step 1: 初始化 benchmark（简化配置）
        print("[Dir3] Step 1: Initializing EvoBenchmark (simplified config)...")
        step1_start = time.time()

        config = {
            "task_suites": ["coding", "reasoning"],  # 2个 suite
            "ablation_configs": ["full"],  # 只跑 full 配置
            "n_runs": 1,
            "max_iterations": 3,  # 每个取3题的效果
            "target_harness": "react_single",
            "target_identity": "dante",
            "output_dir": str(PROJECT_ROOT / "experiments" / "results" / "benchmark"),
        }
        benchmark = EvoBenchmark(config)

        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "init_benchmark",
            "duration": step1_duration,
            "task_suites": config["task_suites"],
            "suites_loaded": {k: len(v) for k, v in benchmark.task_suites.items()},
            "status": "completed",
        })
        print(f"[Dir3] Step 1 completed in {step1_duration:.1f}s")

        # Step 2: 对每个 suite 限制取3题并运行进化
        print("[Dir3] Step 2: Running evolution on each suite (3 tasks each)...")
        step2_start = time.time()

        suite_results = {}
        traces = []
        for suite_name in config["task_suites"]:
            print(f"[Dir3]   Suite: {suite_name}")
            # 限制每个 suite 只取前3题
            original_tasks = benchmark.task_suites.get(suite_name, [])
            benchmark.task_suites[suite_name] = original_tasks[:3]

            full_config = benchmark.ablation_configs.get("full", {"name": "full"})
            sr = benchmark.run_single_evolution(config=full_config, task_suite=suite_name)
            suite_results[suite_name] = sr

            # 收集 trace
            if sr.get("trace"):
                trace = EvolutionTrace(
                    scores=sr["trace"].get("scores", []),
                    token_costs=sr["trace"].get("token_costs", []),
                    decisions=sr["trace"].get("decisions", []),
                    iterations=sr.get("iterations", []),
                    config_name="full",
                    task_suite=suite_name,
                )
                traces.append(trace)

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "run_evolution_suites",
            "duration": step2_duration,
            "suite_results_summary": {
                k: {
                    "final_score": v.get("final_score", 0),
                    "iterations": len(v.get("iterations", [])),
                }
                for k, v in suite_results.items()
            },
            "traces_collected": len(traces),
            "status": "completed",
        })
        print(f"[Dir3] Step 2 completed in {step2_duration:.1f}s")

        # Step 3: 计算所有24项指标
        print("[Dir3] Step 3: Computing all metrics from traces...")
        step3_start = time.time()

        all_metrics = {}
        for trace in traces:
            metrics = compute_all_metrics(trace=trace)
            suite_key = f"{trace.config_name}_{trace.task_suite}"
            all_metrics[suite_key] = metrics.to_dict()

        step3_duration = time.time() - step3_start

        # 汇总所有指标
        flat_metrics = {}
        for suite_key, metric_dict in all_metrics.items():
            for dimension, dim_metrics in metric_dict.items():
                if isinstance(dim_metrics, dict):
                    for metric_name, value in dim_metrics.items():
                        flat_key = f"{suite_key}.{dimension}.{metric_name}"
                        flat_metrics[flat_key] = value

        results["steps"].append({
            "name": "compute_metrics",
            "duration": step3_duration,
            "metrics_per_suite": all_metrics,
            "total_metric_values": len(flat_metrics),
            "status": "completed",
        })
        print(f"[Dir3] Step 3 completed in {step3_duration:.1f}s")
        print(f"[Dir3]   Total metric values computed: {len(flat_metrics)}")

        # Step 4: 运行一轮完整进化循环收集更详细的 trace
        print("[Dir3] Step 4: Running full evolution cycle for detailed trace...")
        step4_start = time.time()

        from self_evolution.engine import run_evolution_cycle
        evo_report = run_evolution_cycle('react_single', 'dante', max_iterations=3)

        step4_duration = time.time() - step4_start
        results["steps"].append({
            "name": "evolution_cycle",
            "duration": step4_duration,
            "initial_score": evo_report.get("initial_score", 0),
            "final_score": evo_report.get("final_score", 0),
            "total_accepted": evo_report.get("total_accepted", 0),
            "status": "completed",
        })
        print(f"[Dir3] Step 4 completed in {step4_duration:.1f}s")

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        results["summary"] = {
            "suites_evaluated": len(suite_results),
            "metrics_computed": len(flat_metrics),
            "evolution_improvement": evo_report.get("final_score", 0) - evo_report.get("initial_score", 0),
        }

    except TimeoutError as e:
        results["status"] = "TIMEOUT"
        results["errors"].append(str(e))
    except Exception as e:
        results["status"] = "FAIL"
        results["errors"].append(f"{type(e).__name__}: {e}")
        results["traceback"] = traceback.format_exc()

    results["end_time"] = results.get("end_time", time.strftime("%Y-%m-%d %H:%M:%S"))
    return results


if __name__ == "__main__":
    results = run_experiment()
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS:")
    print("=" * 60)
    print(json.dumps(results, indent=2, ensure_ascii=False))
