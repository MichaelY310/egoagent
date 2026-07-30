import json


def search_meilisearch(query: str, category: str = "all", limit: int = 10, _context: dict = None):
    """
    Search across all registered tools and knowledge bases using Meilisearch.

    Args:
        query: The search query string
        category: 'tools', 'knowledges', or 'all'
        limit: Max results per category
        _context: Runtime context (injected by agent)
    """
    if not query or not query.strip():
        return json.dumps({"error": "query is empty. Provide a search query."})

    mgr = None
    if _context and "meilisearch" in _context:
        mgr = _context["meilisearch"]

    if mgr is None:
        return json.dumps({
            "error": "Meilisearch is not available. The search service may not be running.",
            "hint": "Start the harness with Meilisearch enabled (default) to use this tool."
        })

    if not mgr.is_running:
        return json.dumps({
            "error": "Meilisearch service is not running.",
            "hint": "The search service may have stopped. Restart the harness."
        })

    try:
        if category == "tools":
            results = {"tools": mgr.search_tools(query, limit=limit), "knowledges": []}
        elif category == "knowledges":
            results = {"tools": [], "knowledges": mgr.search_knowledges(query, limit=limit)}
        else:
            results = mgr.search_all(query, limit=limit)
    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})

    total = len(results.get("tools", [])) + len(results.get("knowledges", []))
    output = {
        "query": query,
        "category": category,
        "total_results": total,
        "tools": results.get("tools", []),
        "knowledges": results.get("knowledges", []),
    }

    if total == 0:
        output["hint"] = "No results found. Try different keywords or check spelling."

    return json.dumps(output, ensure_ascii=False)
