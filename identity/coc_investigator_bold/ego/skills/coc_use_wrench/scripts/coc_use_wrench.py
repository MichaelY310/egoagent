from tabletop.coc_identity import propose_item_use

def coc_use_wrench(target='', intent='', _context=None):
    return propose_item_use(_context, 'wrench', target=target, intent=intent)
