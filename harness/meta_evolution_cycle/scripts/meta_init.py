"""meta_init: Initialize meta-evolution cycle context."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()
    strategy = engine.get_current_strategy()

    meta_report = {
        "target_harness": ctx.get("target_harness", "react_single"),
        "target_identity": ctx.get("target_identity", "dante"),
        "n_inner_cycles": ctx.get("n_inner_cycles", 2),
    }

    return {
        "current_strategy": strategy,
        "meta_report": meta_report,
    }
