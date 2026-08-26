from tabletop.coc_identity import propose_item_use

def coc_use_flashlight(target='', intent='', _context=None):
    return propose_item_use(_context, 'flashlight', target=target, intent=intent)
