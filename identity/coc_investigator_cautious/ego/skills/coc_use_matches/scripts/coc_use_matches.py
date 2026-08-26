from tabletop.coc_identity import propose_item_use

def coc_use_matches(target='', intent='', _context=None):
    return propose_item_use(_context, 'matches', target=target, intent=intent)
