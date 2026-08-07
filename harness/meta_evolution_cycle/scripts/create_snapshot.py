"""create_snapshot: Create a meta-level snapshot of current strategy."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()
    snapshot_id = engine._create_meta_snapshot()

    return {
        "snapshot_id": snapshot_id,
    }
