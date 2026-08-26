from tabletop.coc7 import public_view
from tabletop.coc_identity import load_character_party


SLOTS = {"human": "人类调查员", "investigator_a": "调查员A", "investigator_b": "调查员B"}


def run(ctx):
    identities = ctx.get("_runtime", {}).get("agent_identities", {})
    characters = load_character_party({actor: identities[slot] for actor, slot in SLOTS.items()})
    return {"characters": characters, "public_state": public_view(ctx["state"], characters)}
