#!/usr/bin/env python3
"""
方向2: Identity Persona（身份评估）实验
对 'dante' identity 运行完整的探针评估，并检测漂移
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
        "direction": "dir2_identity_persona",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        from self_evolution.identity_eval import IdentityEvaluator

        # Step 1: 初始化评估器
        print("[Dir2] Step 1: Initializing IdentityEvaluator for 'dante'...")
        step1_start = time.time()
        evaluator = IdentityEvaluator('dante')
        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "init_evaluator",
            "duration": step1_duration,
            "identity": "dante",
            "role": evaluator.role,
            "traits": evaluator.traits,
            "skills_count": len(evaluator.skills),
            "knowledge_count": len(evaluator.knowledge),
            "status": "completed",
        })
        print(f"[Dir2] Step 1 completed in {step1_duration:.1f}s")

        # Step 2: 生成控制探针
        print("[Dir2] Step 2: Generating control probes...")
        step2_start = time.time()
        all_probes = evaluator.generate_control_probes()
        print(f"[Dir2]   Generated {len(all_probes)} total probes")

        # 选10个代表性探针（每个类别选几个）
        selected_probes = []
        categories = {}
        for probe in all_probes:
            cat = probe["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(probe)

        # 每个类别选2-3个，总计10个
        per_cat = max(2, 10 // max(len(categories), 1))
        for cat, probes in categories.items():
            selected_probes.extend(probes[:per_cat])
        selected_probes = selected_probes[:10]

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "generate_probes",
            "duration": step2_duration,
            "total_probes_generated": len(all_probes),
            "selected_probes": len(selected_probes),
            "categories": {cat: len(probes) for cat, probes in categories.items()},
            "probe_ids": [p["id"] for p in selected_probes],
            "status": "completed",
        })
        print(f"[Dir2] Step 2 completed in {step2_duration:.1f}s, selected {len(selected_probes)} probes")

        # Step 3: 运行探针（让 Agent 回答）
        print("[Dir2] Step 3: Running probes (agent responses)...")
        step3_start = time.time()
        probe_results = evaluator.run_probes(selected_probes)
        step3_duration = time.time() - step3_start
        results["steps"].append({
            "name": "run_probes",
            "duration": step3_duration,
            "probes_run": len(probe_results),
            "responses_preview": [
                {"id": r["id"], "response_len": len(r.get("response", ""))}
                for r in probe_results
            ],
            "status": "completed",
        })
        print(f"[Dir2] Step 3 completed in {step3_duration:.1f}s")

        # Step 4: Judge 打分
        print("[Dir2] Step 4: Scoring probe results with LLM judge...")
        step4_start = time.time()
        scores = evaluator.score_probe_results(probe_results)
        step4_duration = time.time() - step4_start
        results["steps"].append({
            "name": "score_results",
            "duration": step4_duration,
            "overall_controllability": scores.get("overall_controllability", 0),
            "personality_consistency": scores.get("personality_consistency", 0),
            "constraint_adherence": scores.get("constraint_adherence", 0),
            "capability_coverage": scores.get("capability_coverage", 0),
            "adversarial_robustness": scores.get("adversarial_robustness", 0),
            "dimension_scores": scores.get("dimension_scores", {}),
            "status": "completed",
        })
        print(f"[Dir2] Step 4 completed in {step4_duration:.1f}s")
        print(f"[Dir2]   Overall controllability: {scores.get('overall_controllability', 0):.3f}")

        # Step 5: 检测漂移（用当前分数作为 baseline，模拟对比）
        print("[Dir2] Step 5: Detecting drift (simulating baseline comparison)...")
        step5_start = time.time()

        # 使用当前分数作为 baseline，模拟微小变化
        baseline_scores = {
            "overall_controllability": scores.get("overall_controllability", 0) + 0.05,
            "personality_consistency": scores.get("personality_consistency", 0) + 0.03,
            "constraint_adherence": scores.get("constraint_adherence", 0) + 0.02,
            "capability_coverage": scores.get("capability_coverage", 0) - 0.01,
            "adversarial_robustness": scores.get("adversarial_robustness", 0) + 0.04,
            "dimension_scores": scores.get("dimension_scores", {}),
        }
        drift = evaluator.detect_drift(baseline_scores, scores)

        step5_duration = time.time() - step5_start
        results["steps"].append({
            "name": "detect_drift",
            "duration": step5_duration,
            "aggregate_drift": drift.get("aggregate_drift", 0),
            "any_tolerance_exceeded": drift.get("any_tolerance_exceeded", False),
            "critical_tolerance_exceeded": drift.get("critical_tolerance_exceeded", False),
            "recommendation": drift.get("recommendation", "unknown"),
            "category_drifts": drift.get("category_drifts", {}),
            "status": "completed",
        })
        print(f"[Dir2] Step 5 completed in {step5_duration:.1f}s")
        print(f"[Dir2]   Drift recommendation: {drift.get('recommendation', 'unknown')}")

        # Step 6: 生成报告
        print("[Dir2] Step 6: Generating report...")
        report = evaluator.generate_report(scores, drift)
        print(report)

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        results["summary"] = {
            "overall_controllability": scores.get("overall_controllability", 0),
            "drift_recommendation": drift.get("recommendation", "unknown"),
            "total_probes": len(selected_probes),
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
