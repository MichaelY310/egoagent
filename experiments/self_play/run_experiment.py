"""
Self-Play Evolution Experiments.

Experiment 1: Fixed Judge vs Evolving Judge comparison
Experiment 2: Random Curriculum vs ZPD Curriculum comparison
Experiment 3: Convergence speed (Tri-role vs Solver-only evolution)

CLI entry point. Outputs JSON results.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from self_evolution.self_play import TriRoleEvolution
from self_evolution.zpd_curriculum import ZPDCurriculum
from self_evolution.judge_calibration import JudgeCalibration
from self_evolution.population_tournament import PopulationTournament
from self_evolution.engine import _llm_call, _save_json, DATA_DIR


RESULTS_DIR = DATA_DIR / "experiment_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def experiment_1_judge_comparison(n_rounds: int = 5) -> Dict:
    """
    Experiment 1: Fixed Judge vs Evolving Judge.

    Compare solver improvement when:
    A) Judge uses a fixed evaluation prompt (no evolution)
    B) Judge co-evolves with Solver (full tri-role)

    Returns:
        Comparison results
    """
    print("=" * 60)
    print("Experiment 1: Fixed Judge vs Evolving Judge")
    print("=" * 60)

    # Condition A: Fixed Judge
    print("\n[Condition A] Running with Fixed Judge...")
    config_fixed = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_fixed = TriRoleEvolution(config_fixed)
    # Override judge evolution to be a no-op
    original_judge_evolve = tri_fixed.judge_evolve
    tri_fixed.judge_evolve = lambda feedback: None  # Disable judge evolution

    results_fixed = []
    for r in range(n_rounds):
        result = tri_fixed.run_self_play_round()
        results_fixed.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}, pass_rate={result['pass_rate']:.2f}")

    # Condition B: Evolving Judge
    print("\n[Condition B] Running with Evolving Judge...")
    config_evolving = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_evolving = TriRoleEvolution(config_evolving)
    # Generate some gold references for calibration
    tri_evolving.calibration.generate_gold_references("AI assistant tasks", n_pairs=3)

    results_evolving = []
    for r in range(n_rounds):
        result = tri_evolving.run_self_play_round()
        results_evolving.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}, pass_rate={result['pass_rate']:.2f}")

    # Comparison
    fixed_final = results_fixed[-1]["avg_score"] if results_fixed else 0.0
    evolving_final = results_evolving[-1]["avg_score"] if results_evolving else 0.0

    comparison = {
        "experiment": "fixed_vs_evolving_judge",
        "n_rounds": n_rounds,
        "fixed_judge": {
            "results": results_fixed,
            "final_score": fixed_final,
        },
        "evolving_judge": {
            "results": results_evolving,
            "final_score": evolving_final,
        },
        "improvement_delta": evolving_final - fixed_final,
        "winner": "evolving" if evolving_final > fixed_final else "fixed",
    }

    print(f"\n[Result] Fixed Judge final: {fixed_final:.3f}, Evolving Judge final: {evolving_final:.3f}")
    print(f"[Result] Winner: {comparison['winner']} (delta: {comparison['improvement_delta']:+.3f})")
    return comparison


def experiment_2_curriculum_comparison(n_rounds: int = 5) -> Dict:
    """
    Experiment 2: Random Curriculum vs ZPD Curriculum.

    Compare solver improvement when:
    A) Tasks are generated randomly (no difficulty targeting)
    B) Tasks target the Zone of Proximal Development

    Returns:
        Comparison results
    """
    print("\n" + "=" * 60)
    print("Experiment 2: Random Curriculum vs ZPD Curriculum")
    print("=" * 60)

    # Condition A: Random Curriculum
    print("\n[Condition A] Running with Random Curriculum...")
    config_random = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_random = TriRoleEvolution(config_random)
    # Override proposer to generate random-difficulty tasks
    original_generate = tri_random.proposer_generate

    def random_generate(context):
        tasks = original_generate(context)
        # Randomize difficulties (ignore ZPD targeting)
        import random
        for t in tasks:
            t["difficulty"] = random.random()
        return tasks

    tri_random.proposer_generate = random_generate

    results_random = []
    for r in range(n_rounds):
        result = tri_random.run_self_play_round()
        results_random.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
            "difficulty": result["difficulty"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}, difficulty={result['difficulty']:.2f}")

    # Condition B: ZPD Curriculum
    print("\n[Condition B] Running with ZPD Curriculum...")
    config_zpd = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_zpd = TriRoleEvolution(config_zpd)

    results_zpd = []
    for r in range(n_rounds):
        result = tri_zpd.run_self_play_round()
        results_zpd.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
            "difficulty": result["difficulty"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}, difficulty={result['difficulty']:.2f}")

    # Comparison
    random_final = results_random[-1]["avg_score"] if results_random else 0.0
    zpd_final = results_zpd[-1]["avg_score"] if results_zpd else 0.0

    # Check if ZPD maintained better pass rate stability
    random_pass_rates = [r["pass_rate"] for r in results_random]
    zpd_pass_rates = [r["pass_rate"] for r in results_zpd]
    random_stability = 1.0 - (max(random_pass_rates) - min(random_pass_rates)) if random_pass_rates else 0.0
    zpd_stability = 1.0 - (max(zpd_pass_rates) - min(zpd_pass_rates)) if zpd_pass_rates else 0.0

    comparison = {
        "experiment": "random_vs_zpd_curriculum",
        "n_rounds": n_rounds,
        "random_curriculum": {
            "results": results_random,
            "final_score": random_final,
            "pass_rate_stability": random_stability,
        },
        "zpd_curriculum": {
            "results": results_zpd,
            "final_score": zpd_final,
            "pass_rate_stability": zpd_stability,
        },
        "score_delta": zpd_final - random_final,
        "stability_delta": zpd_stability - random_stability,
        "winner": "zpd" if zpd_final > random_final else "random",
    }

    print(f"\n[Result] Random final: {random_final:.3f}, ZPD final: {zpd_final:.3f}")
    print(f"[Result] Winner: {comparison['winner']} (delta: {comparison['score_delta']:+.3f})")
    return comparison


def experiment_3_convergence_speed(n_rounds: int = 8) -> Dict:
    """
    Experiment 3: Convergence speed comparison.

    Compare:
    A) Full tri-role co-evolution (Proposer + Solver + Judge evolve)
    B) Solver-only evolution (Proposer and Judge fixed)

    Returns:
        Convergence speed comparison
    """
    print("\n" + "=" * 60)
    print("Experiment 3: Tri-Role vs Solver-Only Convergence")
    print("=" * 60)

    # Condition A: Full tri-role
    print("\n[Condition A] Running Tri-Role Co-evolution...")
    config_tri = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_full = TriRoleEvolution(config_tri)

    results_tri = []
    for r in range(n_rounds):
        result = tri_full.run_self_play_round()
        results_tri.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
            "elo_ratings": result["elo_ratings"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}")

    # Condition B: Solver-only
    print("\n[Condition B] Running Solver-Only Evolution...")
    config_solver = {
        "target_harness": "react_single",
        "target_identity": "dante",
        "max_rounds": n_rounds,
        "tasks_per_round": 3,
        "difficulty_target": 0.5,
    }
    tri_solver_only = TriRoleEvolution(config_solver)
    # Disable Proposer and Judge evolution
    tri_solver_only.proposer_evolve = lambda feedback: None
    tri_solver_only.judge_evolve = lambda feedback: None

    results_solver = []
    for r in range(n_rounds):
        result = tri_solver_only.run_self_play_round()
        results_solver.append({
            "round": r + 1,
            "avg_score": result["avg_score"],
            "pass_rate": result["pass_rate"],
        })
        print(f"  Round {r+1}: score={result['avg_score']:.3f}")

    # Find convergence point (first round where improvement < threshold)
    def find_convergence_round(results: List[Dict], threshold: float = 0.02) -> int:
        for i in range(1, len(results)):
            if abs(results[i]["avg_score"] - results[i-1]["avg_score"]) < threshold:
                # Check if it stays stable for 2 more rounds
                if i + 2 < len(results):
                    subsequent = [results[j]["avg_score"] for j in range(i, min(i+3, len(results)))]
                    var = sum((s - sum(subsequent)/len(subsequent))**2 for s in subsequent) / len(subsequent)
                    if var < threshold:
                        return i + 1
        return len(results)  # Didn't converge

    tri_convergence = find_convergence_round(results_tri)
    solver_convergence = find_convergence_round(results_solver)

    comparison = {
        "experiment": "convergence_tri_vs_solver_only",
        "n_rounds": n_rounds,
        "tri_role": {
            "results": results_tri,
            "final_score": results_tri[-1]["avg_score"] if results_tri else 0.0,
            "convergence_round": tri_convergence,
        },
        "solver_only": {
            "results": results_solver,
            "final_score": results_solver[-1]["avg_score"] if results_solver else 0.0,
            "convergence_round": solver_convergence,
        },
        "faster_convergence": "tri_role" if tri_convergence < solver_convergence else "solver_only",
        "score_delta": (results_tri[-1]["avg_score"] - results_solver[-1]["avg_score"])
                       if results_tri and results_solver else 0.0,
    }

    print(f"\n[Result] Tri-role converged at round {tri_convergence}, Solver-only at round {solver_convergence}")
    print(f"[Result] Faster: {comparison['faster_convergence']}")
    return comparison


def run_all_experiments(n_rounds: int = 5) -> Dict:
    """Run all experiments and return combined results."""
    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_rounds_per_experiment": n_rounds,
        "experiments": {},
    }

    try:
        results["experiments"]["exp1_judge"] = experiment_1_judge_comparison(n_rounds)
    except Exception as e:
        results["experiments"]["exp1_judge"] = {"error": str(e)}
        print(f"[ERROR] Experiment 1 failed: {e}")

    try:
        results["experiments"]["exp2_curriculum"] = experiment_2_curriculum_comparison(n_rounds)
    except Exception as e:
        results["experiments"]["exp2_curriculum"] = {"error": str(e)}
        print(f"[ERROR] Experiment 2 failed: {e}")

    try:
        results["experiments"]["exp3_convergence"] = experiment_3_convergence_speed(n_rounds)
    except Exception as e:
        results["experiments"]["exp3_convergence"] = {"error": str(e)}
        print(f"[ERROR] Experiment 3 failed: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Self-Play Evolution Experiments"
    )
    parser.add_argument(
        "--experiment", "-e",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which experiment to run (1=Judge, 2=Curriculum, 3=Convergence, all=all)"
    )
    parser.add_argument(
        "--rounds", "-r",
        type=int,
        default=5,
        help="Number of rounds per experiment (default: 5)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file path (default: auto-generated in data/experiment_results/)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verbose output"
    )

    args = parser.parse_args()

    if args.quiet:
        import io
        sys.stdout = io.StringIO()

    # Run selected experiment(s)
    if args.experiment == "1":
        results = {"experiments": {"exp1_judge": experiment_1_judge_comparison(args.rounds)}}
    elif args.experiment == "2":
        results = {"experiments": {"exp2_curriculum": experiment_2_curriculum_comparison(args.rounds)}}
    elif args.experiment == "3":
        results = {"experiments": {"exp3_convergence": experiment_3_convergence_speed(args.rounds)}}
    else:
        results = run_all_experiments(args.rounds)

    if args.quiet:
        sys.stdout = sys.__stdout__

    # Add metadata
    results["metadata"] = {
        "experiment_selected": args.experiment,
        "rounds": args.rounds,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Save results
    output_path = args.output
    if not output_path:
        output_path = str(RESULTS_DIR / f"selfplay_exp_{time.strftime('%Y%m%d_%H%M%S')}.json")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Results saved to: {output_path}")
    print(f"{'='*60}")

    # Print summary JSON to stdout
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
