from tabletop.coc7 import STATE_SCHEMA, scenario
from tabletop.coc_identity import load_character_party, sync_equipment_tools


SLOTS = {"human": "人类调查员", "investigator_a": "调查员A", "investigator_b": "调查员B"}


def run(ctx):
    identities = ctx.get("_runtime", {}).get("agent_identities", {})
    missing = [slot for slot in SLOTS.values() if slot not in identities]
    if missing:
        raise ValueError(f"CoC harness requires character-card Identity slots: {missing}")
    bindings = {actor: identities[slot] for actor, slot in SLOTS.items()}
    for path in bindings.values():
        sync_equipment_tools(path)
    return {
        "scenario_state": scenario("the_haunting"),
        "state_schema": STATE_SCHEMA,
        "characters": load_character_party(bindings),
    }
