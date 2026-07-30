"""Execute a full self-evolution cycle."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from self_evolution.engine import SelfEvolutionEngine

def run(target_harness: str, target_identity: str, max_iterations: int = 3) -> str:
    import json
    engine = SelfEvolutionEngine()
    report = engine.run_evolution_cycle(
        target_harness=target_harness,
        target_identity=target_identity,
        max_iterations=int(max_iterations),
    )
    # Format summary
    summary = {
        "status": "completed",
        "initial_score": report["initial_score"],
        "final_score": report["final_score"],
        "improvement": report["final_score"] - report["initial_score"],
        "iterations": len(report["iterations"]),
        "accepted": report["total_accepted"],
        "rejected": report["total_rejected"],
        "rollbacks": report["total_rollbacks"],
        "details": report["iterations"],
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)
