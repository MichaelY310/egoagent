#!/usr/bin/env python3
"""
方向1: Meta-Evolution（元进化）实验
运行完整的 meta evolution step + 内部进化循环
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
signal.alarm(3500)  # 略小于1小时

# ============================================================
# 实验主体
# ============================================================
def run_experiment():
    results = {
        "direction": "dir1_meta_evolution",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        # Step 1: 运行一轮内部进化循环
        print("[Dir1] Step 1: Running inner evolution cycle...")
        step1_start = time.time()

        from self_evolution.engine import run_evolution_cycle
        evo_report = run_evolution_cycle('react_single', 'dante', max_iterations=3)

        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "inner_evolution_cycle",
            "duration": step1_duration,
            "initial_score": evo_report.get("initial_score", 0),
            "final_score": evo_report.get("final_score", 0),
            "accepted": evo_report.get("total_accepted", 0),
            "rejected": evo_report.get("total_rejected", 0),
            "rollbacks": evo_report.get("total_rollbacks", 0),
            "status": "completed",
        })
        print(f"[Dir1] Step 1 completed in {step1_duration:.1f}s")

        # Step 2: 运行 meta evolution step
        print("[Dir1] Step 2: Running meta evolution step...")
        step2_start = time.time()

        from self_evolution.meta_evolution import MetaEvolutionEngine
        meta_engine = MetaEvolutionEngine()

        # 2a: 分析历史
        history_analysis = meta_engine.analyze_evolution_history()
        print(f"[Dir1]   History: {history_analysis['total_attempts']} attempts, "
              f"accept_rate={history_analysis['accept_rate']:.2%}")

        # 2b: 计算 meta gradient
        meta_gradient = meta_engine.compute_meta_gradient(history_analysis)
        print(f"[Dir1]   Meta gradient: {meta_gradient}")

        # 2c: 应用 meta gradient
        if meta_gradient:
            new_strategy = meta_engine.apply_meta_gradient(meta_gradient)
            print(f"[Dir1]   New strategy applied")
        else:
            new_strategy = meta_engine.get_current_strategy()
            print(f"[Dir1]   No gradient computed, keeping current strategy")

        # 2d: 验证 - 再跑一轮内部进化
        print("[Dir1]   Verification: running inner cycle with new strategy...")
        verify_report = run_evolution_cycle('react_single', 'dante', max_iterations=2)

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "meta_evolution_step",
            "duration": step2_duration,
            "history_analysis": {
                "total_attempts": history_analysis["total_attempts"],
                "accept_rate": history_analysis["accept_rate"],
                "avg_improvement": history_analysis["avg_improvement"],
            },
            "meta_gradient": meta_gradient,
            "new_strategy_summary": {k: v for k, v in new_strategy.items() if k != "judge_prompt"},
            "verification_score": verify_report.get("final_score", 0),
            "status": "completed",
        })
        print(f"[Dir1] Step 2 completed in {step2_duration:.1f}s")

        # Step 3: 运行完整的 meta evolution cycle (inner_cycles=1)
        print("[Dir1] Step 3: Running full meta evolution cycle (inner_cycles=1)...")
        step3_start = time.time()

        meta_report = meta_engine.run_meta_evolution_cycle(
            n_inner_cycles=1,
            target_harness='react_single',
            target_identity='dante',
            verbose=True,
        )

        step3_duration = time.time() - step3_start
        results["steps"].append({
            "name": "full_meta_evolution_cycle",
            "duration": step3_duration,
            "decision": meta_report.get("decision", "unknown"),
            "old_score": meta_report.get("old_performance", {}).get("final_score", 0),
            "new_score": meta_report.get("new_performance", {}).get("final_score", 0),
            "status": "completed",
        })
        print(f"[Dir1] Step 3 completed in {step3_duration:.1f}s")

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

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
