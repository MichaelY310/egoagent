"""analyze_history: Analyze evolution history statistics."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()
    analysis = engine.analyze_evolution_history()

    return {
        "history_analysis": analysis,
    }
