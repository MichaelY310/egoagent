"""meta_gate: Meta-level gate decision — accept/reject/rollback new strategy."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def run(ctx):
    from self_evolution.meta_evolution import MetaEvolutionEngine

    engine = MetaEvolutionEngine()

    old_params = ctx.get("current_strategy", {})
    new_params = ctx.get("new_strategy", {})
    old_performance = ctx.get("old_performance", {})
    new_performance = ctx.get("new_performance", {})
    snapshot_id = ctx.get("snapshot_id", "")

    decision = engine.meta_gate_decision(old_params, new_params, old_performance, new_performance)

    if decision in ("reject", "rollback"):
        engine._restore_meta_snapshot(snapshot_id)
        current_strategy = old_params
    else:
        current_strategy = new_params

    return {
        "meta_decision": decision,
        "current_strategy": current_strategy,
    }
