from tabletop.coc_identity import propose_item_use

def coc_use_notebook(target='', intent='', _context=None):
    return propose_item_use(_context, 'notebook', target=target, intent=intent)
