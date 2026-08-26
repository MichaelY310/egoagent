import json

from web_access import search_public_web


def web_search(
    query: str,
    max_results: int = 5,
    domains=None,
    exclude_domains=None,
    freshness: str = "",
    search_type: str = "web",
):
    result = search_public_web(
        query,
        max_results=max_results,
        domains=domains,
        exclude_domains=exclude_domains,
        freshness=freshness,
        search_type=search_type,
    )
    return json.dumps(result, ensure_ascii=False)
