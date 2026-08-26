from tabletop.coc_identity import propose_item_use

def coc_use_camera(target='', intent='', _context=None):
    return propose_item_use(_context, 'camera', target=target, intent=intent)
