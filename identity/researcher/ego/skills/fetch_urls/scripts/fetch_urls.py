import json

from web_access import fetch_public_urls


def fetch_urls(urls, max_chars_per_url: int = 12000, total_max_chars: int = 40000):
    return json.dumps(
        fetch_public_urls(
            urls,
            max_chars_per_url=max_chars_per_url,
            total_max_chars=total_max_chars,
        ),
        ensure_ascii=False,
    )
