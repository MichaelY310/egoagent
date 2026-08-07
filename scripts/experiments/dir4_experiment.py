#!/usr/bin/env python3
"""
方向4: Pipeline Architecture Search（架构搜索）实验
运行 mutation 策略 2 代种群搜索，每代评估（用 LLM 对 DAG 结构打分）
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
        "direction": "dir4_pipeline_architecture_search",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        from experiments.pipeline_search.search_engine import PipelineArchitectureSearch

        # Step 1: 初始化搜索引擎
        print("[Dir4] Step 1: Initializing PipelineArchitectureSearch...")
        step1_start = time.time()

        search_config = {
            "search_strategy": "mutation",
            "population_size": 5,  # 小种群加速实验
            "max_generations": 2,  # 2代
            "eval_tasks": [
                "完成一个多步骤编程任务",
                "分析文本并提取关键信息",
                "解决一个需要工具使用的问题",
            ],
            "mutation_rate": 0.7,
            "crossover_rate": 0.3,
            "harness_dir": str(PROJECT_ROOT / "harness"),
            "output_dir": str(PROJECT_ROOT / "experiments" / "results" / "pipeline_search"),
            "elite_ratio": 0.2,
        }
        search = PipelineArchitectureSearch(search_config)

        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "init_search",
            "duration": step1_duration,
            "config": {k: v for k, v in search_config.items() if k != "harness_dir"},
            "status": "completed",
        })
        print(f"[Dir4] Step 1 completed in {step1_duration:.1f}s")

        # Step 2: 运行完整搜索
        print("[Dir4] Step 2: Running population search (2 generations)...")
        step2_start = time.time()

        search_result = search.run_search()

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "run_search",
            "duration": step2_duration,
            "best_fitness": search_result.get("best_fitness", 0),
            "search_trace": search_result.get("search_trace", []),
            "population_size": len(search_result.get("population", [])),
            "best_pipeline_name": search_result.get("best_pipeline", {}).get("name", "unknown")
                if search_result.get("best_pipeline") else "none",
            "status": "completed",
        })
        print(f"[Dir4] Step 2 completed in {step2_duration:.1f}s")
        print(f"[Dir4]   Best fitness: {search_result.get('best_fitness', 0):.3f}")

        # Step 3: 验证最佳 pipeline
        print("[Dir4] Step 3: Validating best pipeline...")
        step3_start = time.time()

        best_pipeline = search_result.get("best_pipeline")
        validation_result = {"valid": False, "message": "No pipeline found"}
        if best_pipeline:
            valid, msg = search.validate_pipeline(best_pipeline)
            validation_result = {"valid": valid, "message": msg}
            print(f"[Dir4]   Validation: {'PASS' if valid else 'FAIL'} - {msg}")

        step3_duration = time.time() - step3_start
        results["steps"].append({
            "name": "validate_best",
            "duration": step3_duration,
            "validation": validation_result,
            "status": "completed",
        })
        print(f"[Dir4] Step 3 completed in {step3_duration:.1f}s")

        # Step 4: 评估最佳 pipeline 分数
        print("[Dir4] Step 4: Evaluating best pipeline on tasks...")
        step4_start = time.time()

        eval_score = 0.0
        if best_pipeline:
            eval_score = search.evaluate_pipeline(best_pipeline, search_config["eval_tasks"])
            print(f"[Dir4]   Evaluation score: {eval_score:.3f}")

        step4_duration = time.time() - step4_start
        results["steps"].append({
            "name": "evaluate_best",
            "duration": step4_duration,
            "eval_score": eval_score,
            "status": "completed",
        })
        print(f"[Dir4] Step 4 completed in {step4_duration:.1f}s")

        # Step 5: 获取种群统计
        print("[Dir4] Step 5: Collecting population statistics...")
        population = search.get_population()
        fitness_values = [ind.get("fitness", 0) for ind in population if isinstance(ind, dict)]
        if not fitness_values:
            # population might return Individual objects
            fitness_values = [search_result.get("best_fitness", 0)]

        results["steps"].append({
            "name": "population_stats",
            "duration": 0,
            "population_count": len(population),
            "fitness_values": fitness_values[:10],
            "avg_fitness": sum(fitness_values) / len(fitness_values) if fitness_values else 0,
            "status": "completed",
        })

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        results["summary"] = {
            "generations_completed": 2,
            "best_fitness": search_result.get("best_fitness", 0),
            "population_size": len(population),
            "best_valid": validation_result.get("valid", False),
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
