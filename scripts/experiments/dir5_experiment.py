#!/usr/bin/env python3
"""
方向5: Lifelong Learning（持续学习）实验
运行一轮完整的进化循环，然后从轨迹中提炼原则、检测冲突、
新颖度过滤、经验缓冲区回放
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
        "direction": "dir5_lifelong_learning",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        # Step 1: 运行一轮进化循环，产生轨迹
        print("[Dir5] Step 1: Running evolution cycle to generate trajectory...")
        step1_start = time.time()

        from self_evolution.engine import run_evolution_cycle, DATA_DIR
        evo_report = run_evolution_cycle('react_single', 'dante', max_iterations=3)

        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "evolution_cycle",
            "duration": step1_duration,
            "initial_score": evo_report.get("initial_score", 0),
            "final_score": evo_report.get("final_score", 0),
            "iterations": len(evo_report.get("iterations", [])),
            "status": "completed",
        })
        print(f"[Dir5] Step 1 completed in {step1_duration:.1f}s")

        # Step 2: 从轨迹中提炼原则
        print("[Dir5] Step 2: Distilling principles from trajectory...")
        step2_start = time.time()

        from self_evolution.engine import distill_principles
        session_dir = DATA_DIR / "_temp_session"
        new_principles = []
        if session_dir.exists() and (session_dir / "messages.json").exists():
            new_principles = distill_principles(str(session_dir))
        print(f"[Dir5]   Distilled {len(new_principles)} new principles")

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "distill_principles",
            "duration": step2_duration,
            "new_principles_count": len(new_principles),
            "principles_preview": [p.get("description", "")[:100] for p in new_principles[:5]],
            "status": "completed",
        })
        print(f"[Dir5] Step 2 completed in {step2_duration:.1f}s")

        # Step 3: 检测原则冲突
        print("[Dir5] Step 3: Detecting principle conflicts...")
        step3_start = time.time()

        from self_evolution.principle_manager import PrincipleManager
        pm = PrincipleManager()
        conflicts = pm.detect_conflicts()
        print(f"[Dir5]   Found {len(conflicts)} conflicts")

        # 尝试解决第一个冲突
        resolved = None
        if conflicts:
            p1, p2, score = conflicts[0]
            print(f"[Dir5]   Resolving top conflict (score={score:.2f})...")
            resolved = pm.resolve_conflict(p1, p2)

        step3_duration = time.time() - step3_start
        results["steps"].append({
            "name": "detect_conflicts",
            "duration": step3_duration,
            "conflicts_found": len(conflicts),
            "top_conflict_score": conflicts[0][2] if conflicts else 0,
            "resolved": resolved.get("description", None) if resolved else None,
            "status": "completed",
        })
        print(f"[Dir5] Step 3 completed in {step3_duration:.1f}s")

        # Step 4: 新颖度过滤（Predictive Distillation）
        print("[Dir5] Step 4: Novelty filtering (predictive distillation)...")
        step4_start = time.time()

        from self_evolution.predictive_distill import PredictiveDistiller
        distiller = PredictiveDistiller(novelty_threshold=0.3)

        # 运行预测性蒸馏
        novel_principles = []
        if session_dir.exists() and (session_dir / "messages.json").exists():
            novel_principles = distiller.predictive_distill(str(session_dir))
        print(f"[Dir5]   Novel principles after filtering: {len(novel_principles)}")

        step4_duration = time.time() - step4_start
        results["steps"].append({
            "name": "novelty_filtering",
            "duration": step4_duration,
            "novel_principles_count": len(novel_principles),
            "novelty_threshold": 0.3,
            "status": "completed",
        })
        print(f"[Dir5] Step 4 completed in {step4_duration:.1f}s")

        # Step 5: 经验缓冲区回放
        print("[Dir5] Step 5: Experience buffer replay...")
        step5_start = time.time()

        from self_evolution.experience_buffer import ExperienceBuffer, Experience

        buffer = ExperienceBuffer(max_size=100)

        # 添加当前进化轨迹作为经验
        for i, iteration in enumerate(evo_report.get("iterations", [])):
            exp = Experience(
                trajectory_summary=f"Evolution iteration {i+1}: {iteration.get('action', '')}",
                task_description=f"Evolution step {i+1}",
                outcome="success" if iteration.get("decision") == "accept" else "failure",
                score=iteration.get("score_after", 0.5),
                domain="evolution",
            )
            buffer.add(exp)

        # 优先级采样回放
        sampled = buffer.sample(n=5, strategy='priority')
        print(f"[Dir5]   Buffer size: {buffer.size()}, sampled: {len(sampled)}")

        step5_duration = time.time() - step5_start
        results["steps"].append({
            "name": "experience_replay",
            "duration": step5_duration,
            "buffer_size": buffer.size(),
            "sampled_count": len(sampled),
            "sampled_outcomes": [e.outcome for e in sampled],
            "sampled_scores": [e.score for e in sampled],
            "status": "completed",
        })
        print(f"[Dir5] Step 5 completed in {step5_duration:.1f}s")

        # Step 6: 原则库统计
        print("[Dir5] Step 6: Principle library stats...")
        pm.reload()
        stats = pm.get_stats()
        results["steps"].append({
            "name": "principle_stats",
            "duration": 0,
            "total_principles": stats.get("total_count", 0),
            "by_type": stats.get("by_type", {}),
            "avg_score": stats.get("avg_score", 0),
            "num_clusters": stats.get("num_clusters", 0),
            "status": "completed",
        })
        print(f"[Dir5]   Total principles: {stats.get('total_count', 0)}")

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        results["summary"] = {
            "evolution_improvement": evo_report.get("final_score", 0) - evo_report.get("initial_score", 0),
            "principles_distilled": len(new_principles),
            "conflicts_found": len(conflicts),
            "novel_principles": len(novel_principles),
            "buffer_size": buffer.size(),
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
