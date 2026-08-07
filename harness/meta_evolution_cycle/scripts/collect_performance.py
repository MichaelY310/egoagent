"""collect_performance: Run evolution cycle and collect performance metrics."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.engine import run_evolution_cycle

    target_harness = ctx.get("target_harness", "react_single")
    target_identity = ctx.get("target_identity", "dante")
    n_inner_cycles = ctx.get("n_inner_cycles", 2)

    performance = run_evolution_cycle(
        target_harness=target_harness,
        target_identity=target_identity,
        max_iterations=n_inner_cycles,
        verbose=False,
    )

    # Return under a generic key; the DAG output_vars mapping decides the name
    return {
        "old_performance": performance,
        "new_performance": performance,
    }
