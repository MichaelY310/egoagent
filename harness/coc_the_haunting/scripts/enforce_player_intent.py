from tabletop.coc7 import enforce_player_intent


def run(ctx):
    return enforce_player_intent(ctx["plan"], ctx["human_action"], ctx["public_state"])
