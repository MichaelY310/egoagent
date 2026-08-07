"""apply_meta_gradient: Apply meta-gradient to evolution strategy with safety bounds."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()
    meta_gradient = ctx.get("meta_gradient", {})

    if not isinstance(meta_gradient, dict):
        meta_gradient = {}

    new_strategy = engine.apply_meta_gradient(meta_gradient)

    return {
        "new_strategy": new_strategy,
    }
