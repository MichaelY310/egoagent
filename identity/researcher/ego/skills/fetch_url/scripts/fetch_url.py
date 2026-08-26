import json

from web_access import fetch_public_url


def fetch_url(url: str, max_chars: int = 20000):
    return json.dumps(fetch_public_url(url, max_chars=max_chars), ensure_ascii=False)
