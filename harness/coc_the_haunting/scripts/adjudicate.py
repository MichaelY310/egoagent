from tabletop.coc7 import adjudicate


def run(ctx):
    return adjudicate(ctx["state"], ctx["plan"], ctx["characters"])
