from tabletop.coc_identity import propose_item_use

def coc_use_rope(target='', intent='', _context=None):
    return propose_item_use(_context, 'rope', target=target, intent=intent)
