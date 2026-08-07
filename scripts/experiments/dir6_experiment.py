#!/usr/bin/env python3
"""
方向6: Multi-Agent Self-Play（多角色博弈）实验
运行 TriRoleEvolution 的 Proposer/Solver/Judge 共进化
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
        "direction": "dir6_multi_agent_self_play",
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "errors": [],
    }

    try:
        from self_evolution.self_play import TriRoleEvolution

        # Step 1: 初始化 TriRoleEvolution
        print("[Dir6] Step 1: Initializing TriRoleEvolution...")
        step1_start = time.time()

        config = {
            'target_harness': 'react_single',
            'target_identity': 'dante',
            'max_rounds': 2,
            'tasks_per_round': 3,
        }
        tri_evo = TriRoleEvolution(config)

        step1_duration = time.time() - step1_start
        results["steps"].append({
            "name": "init_tri_role",
            "duration": step1_duration,
            "config": config,
            "initial_elo": dict(tri_evo.elo_ratings),
            "initial_difficulty": tri_evo.proposer_difficulty,
            "status": "completed",
        })
        print(f"[Dir6] Step 1 completed in {step1_duration:.1f}s")
        print(f"[Dir6]   Initial ELO: {tri_evo.elo_ratings}")

        # Step 2: 运行 tournament（Proposer/Solver/Judge 共进化）
        print("[Dir6] Step 2: Running tournament (2 rounds, 3 tasks/round)...")
        step2_start = time.time()

        tournament_result = tri_evo.run_tournament(n_rounds=2)

        step2_duration = time.time() - step2_start
        results["steps"].append({
            "name": "run_tournament",
            "duration": step2_duration,
            "rounds_played": tournament_result.get("n_rounds_played", 0),
            "final_elo": tournament_result.get("final_elo", {}),
            "avg_score_trend": tournament_result.get("avg_score_trend", []),
            "pass_rate_trend": tournament_result.get("pass_rate_trend", []),
            "difficulty_trend": tournament_result.get("difficulty_trend", []),
            "final_avg_score": tournament_result.get("final_avg_score", 0),
            "converged": tournament_result.get("converged", False),
            "improvement": tournament_result.get("improvement", 0),
            "status": "completed",
        })
        print(f"[Dir6] Step 2 completed in {step2_duration:.1f}s")
        print(f"[Dir6]   Rounds played: {tournament_result.get('n_rounds_played', 0)}")
        print(f"[Dir6]   Final avg score: {tournament_result.get('final_avg_score', 0):.3f}")
        print(f"[Dir6]   Final ELO: {tournament_result.get('final_elo', {})}")

        # Step 3: 获取进化动力学
        print("[Dir6] Step 3: Collecting evolution dynamics...")
        step3_start = time.time()

        dynamics = tri_evo.get_evolution_dynamics()

        step3_duration = time.time() - step3_start
        results["steps"].append({
            "name": "evolution_dynamics",
            "duration": step3_duration,
            "n_rounds_completed": dynamics.get("n_rounds_completed", 0),
            "elo_ratings": dynamics.get("elo_ratings", {}),
            "difficulty_curve": dynamics.get("difficulty_curve", []),
            "solver_curve": dynamics.get("solver_capability_curve", []),
            "convergence": dynamics.get("convergence", False),
            "status": "completed",
        })
        print(f"[Dir6] Step 3 completed in {step3_duration:.1f}s")

        # Step 4: 计算 ELO 变化
        print("[Dir6] Step 4: Computing ELO rating changes...")
        initial_elo = config.get("initial_elo", {"proposer": 1500, "solver": 1500, "judge": 1500})
        final_elo = tournament_result.get("final_elo", {})
        elo_changes = {
            role: final_elo.get(role, 1500) - 1500
            for role in ["proposer", "solver", "judge"]
        }

        results["steps"].append({
            "name": "elo_analysis",
            "duration": 0,
            "elo_changes": elo_changes,
            "dominant_role": max(elo_changes, key=elo_changes.get) if elo_changes else "none",
            "status": "completed",
        })
        print(f"[Dir6]   ELO changes: {elo_changes}")

        results["status"] = "PASS"
        results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        results["summary"] = {
            "rounds_played": tournament_result.get("n_rounds_played", 0),
            "final_avg_score": tournament_result.get("final_avg_score", 0),
            "improvement": tournament_result.get("improvement", 0),
            "converged": tournament_result.get("converged", False),
            "final_elo": final_elo,
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
