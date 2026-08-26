from pipeline_engine import _apply_state_transition
from tabletop.coc_identity import apply_character_transactions


ACTOR_SLOTS = {"human": "人类调查员", "investigator_a": "调查员A", "investigator_b": "调查员B"}


def run(ctx):
    world = _apply_state_transition(ctx["state"], ctx["transition"], schema=ctx["schema"])
    if not world.get("accepted"):
        raise ValueError(f"CoC world transaction rejected: {world.get('reason_codes', [])}")
    card_result = apply_character_transactions(ctx.get("character_transactions", []))
    changed_slots = [ACTOR_SLOTS[actor] for actor in card_result.get("changed", []) if actor in ACTOR_SLOTS]
    return {
        "commit_result": {"accepted": True, "state": world["state"], "character_result": card_result},
        "_reload_identity_slots": changed_slots,
    }
