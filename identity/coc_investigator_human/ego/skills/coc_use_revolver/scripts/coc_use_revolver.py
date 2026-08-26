from tabletop.coc_identity import propose_item_use

def coc_use_revolver(target='', intent='', _context=None):
    return propose_item_use(_context, 'revolver', target=target, intent=intent)
