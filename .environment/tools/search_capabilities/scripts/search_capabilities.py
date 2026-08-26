"""Progressively disclose reusable capabilities without loading their code."""

from capability_registry import registry_from_context


def search_capabilities(query: str, kinds=None, limit: int = 6, mode: str = "auto", _context=None):
    registry = registry_from_context(_context)
    # Reindex is cheap for the current catalog and makes newly evolved skills
    # discoverable during the same session.
    registry.reindex()
    return registry.search(query, kinds=kinds, limit=limit, mode=mode)
