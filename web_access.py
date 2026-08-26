"""Safe, dependency-free primitives for public web search and page reading.

The executable EGO tools are intentionally thin wrappers around this module so
search, single-page fetch and batch evidence collection share one URL policy
and one result format.  Network permission is still enforced by the Agent
runtime before any wrapper is imported or executed.
"""

from __future__ import annotations

import html
import gzip
import io
import ipaddress
import re
import socket
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from xml.etree import ElementTree


USER_AGENT = "Mozilla/5.0 (compatible; EgoAgentResearch/2.0; +https://github.com/)"
MAX_RESPONSE_BYTES = 2_000_000
SUPPORTED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/json",
}

_DROP = re.compile(
    r"<(script|style|svg|nav|footer|noscript|template)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_BLOCK = re.compile(
    r"</?(?:p|div|article|section|main|h[1-6]|li|tr|br|blockquote|pre)\b[^>]*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_DDG_RESULT = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", fragment or ""))).strip()


def html_to_text(page: str) -> str:
    page = _DROP.sub(" ", page)
    page = _BLOCK.sub("\n", page)
    page = _TAG.sub(" ", page)
    page = html.unescape(page)
    lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines()]
    return "\n".join(line for line in lines if line)


def public_url(value: str) -> tuple[bool, str]:
    """Resolve a URL and reject local, reserved and credential-bearing targets."""

    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError as error:
        return False, f"invalid URL: {error}"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "only public http(s) URLs are allowed"
    if parsed.username is not None or parsed.password is not None:
        return False, "credentials in URLs are blocked"
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
        if not addresses:
            return False, "host did not resolve to an address"
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                return False, "local, private and reserved network addresses are blocked"
    except (OSError, ValueError) as error:
        return False, f"cannot resolve host: {error}"
    return True, ""


class SafeRedirectHandler(HTTPRedirectHandler):
    """Apply the public-network boundary before following every redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 - urllib API
        target = urljoin(req.full_url, newurl)
        allowed, reason = public_url(target)
        if not allowed:
            raise HTTPError(target, code, f"unsafe redirect blocked: {reason}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _normalize_domains(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = re.split(r"[,\s]+", values)
    if not isinstance(values, (list, tuple, set)):
        return []
    normalized = []
    for value in values:
        raw = str(value or "").strip().lower()
        if "://" in raw:
            raw = urlparse(raw).hostname or ""
        raw = raw.strip("./")
        if raw.startswith("www."):
            raw = raw[4:]
        if _DOMAIN.fullmatch(raw) and raw not in normalized:
            normalized.append(raw)
    return normalized[:10]


def _freshness_date(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    days = {"day": 1, "week": 7, "month": 30, "year": 365}.get(raw)
    if days:
        return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    return None


def build_search_query(query: str, *, domains=None, exclude_domains=None, freshness=None) -> str:
    parts = [str(query or "").strip()]
    included = _normalize_domains(domains)
    excluded = _normalize_domains(exclude_domains)
    if included:
        site_query = " OR ".join(f"site:{domain}" for domain in included)
        parts.append(f"({site_query})" if len(included) > 1 else site_query)
    parts.extend(f"-site:{domain}" for domain in excluded)
    after = _freshness_date(freshness)
    if after:
        parts.append(f"after:{after}")
    return " ".join(part for part in parts if part)


def _result_url(value: str) -> str:
    value = html.unescape(value or "")
    parsed = urlparse(value)
    redirected = parse_qs(parsed.query).get("uddg")
    return unquote(redirected[0]) if redirected else value


def _published(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError):
        return str(value).strip()


def _search_bing_rss(query: str, limit: int, search_type: str) -> list[dict]:
    endpoint = "https://www.bing.com/news/search" if search_type == "news" else "https://www.bing.com/search"
    request = Request(f"{endpoint}?format=rss&q={quote_plus(query)}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        page = response.read(MAX_RESPONSE_BYTES)
    root = ElementTree.fromstring(page)
    results = []
    for item in root.findall("./channel/item")[:limit]:
        results.append(
            {
                "title": clean_text(item.findtext("title", "")),
                "url": str(item.findtext("link", "") or "").strip(),
                "snippet": clean_text(item.findtext("description", "")),
                "published_at": _published(item.findtext("pubDate", "")),
                "provider": "bing_rss",
            }
        )
    return results


def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    request = Request(
        "https://html.duckduckgo.com/html/?q=" + quote_plus(query),
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=20) as response:
        page = response.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
    return [
        {
            "title": clean_text(title),
            "url": _result_url(url),
            "snippet": clean_text(snippet),
            "published_at": "",
            "provider": "duckduckgo_html",
        }
        for url, title, snippet in _DDG_RESULT.findall(page)[:limit]
    ]


def search_public_web(
    query: str,
    max_results: int = 5,
    domains=None,
    exclude_domains=None,
    freshness: str | None = None,
    search_type: str = "web",
) -> dict:
    """Search the public web and return normalized, citation-ready results."""

    original_query = str(query or "").strip()
    if not original_query:
        return {"ok": False, "error": "query is empty", "results": []}
    limit = max(1, min(int(max_results or 5), 10))
    kind = str(search_type or "web").strip().lower()
    if kind not in {"web", "news"}:
        return {"ok": False, "error": "search_type must be 'web' or 'news'", "results": []}
    effective_query = build_search_query(
        original_query,
        domains=domains,
        exclude_domains=exclude_domains,
        freshness=freshness,
    )
    included_domains = _normalize_domains(domains)
    excluded_domains = _normalize_domains(exclude_domains)
    errors = []
    try:
        raw_results = _search_bing_rss(effective_query, limit, kind)
    except Exception as error:  # network providers fail independently
        errors.append(f"Bing RSS: {error}")
        try:
            raw_results = _search_duckduckgo(effective_query, limit)
        except Exception as fallback_error:
            errors.append(f"DuckDuckGo HTML: {fallback_error}")
            return {
                "ok": False,
                "query": original_query,
                "effective_query": effective_query,
                "search_type": kind,
                "error": "web search failed",
                "provider_errors": errors,
                "results": [],
            }

    results = []
    seen = set()
    for item in raw_results:
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        hostname = parsed.hostname.lower()
        if included_domains and not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in included_domains
        ):
            continue
        if any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in excluded_domains
        ):
            continue
        canonical = parsed._replace(fragment="").geturl()
        if canonical in seen:
            continue
        seen.add(canonical)
        results.append(
            {
                "id": f"S{len(results) + 1}",
                "title": str(item.get("title") or "").strip(),
                "url": canonical,
                "domain": hostname,
                "snippet": str(item.get("snippet") or "").strip(),
                "published_at": str(item.get("published_at") or "").strip(),
                "provider": str(item.get("provider") or "unknown"),
            }
        )
        if len(results) >= limit:
            break
    return {
        "ok": True,
        "query": original_query,
        "effective_query": effective_query,
        "search_type": kind,
        "retrieved_at": utc_now(),
        "results": results,
        "citation_hint": "Cite claims with the source URL; use ids S1, S2, ... while reasoning.",
        **({"provider_warnings": errors} if errors else {}),
    }


def fetch_public_url(url: str, max_chars: int = 20_000) -> dict:
    """Fetch one public page with redirect validation and bounded output."""

    requested_url = str(url or "").strip()
    allowed, reason = public_url(requested_url)
    if not allowed:
        return {"ok": False, "url": requested_url, "error": reason}
    limit = max(1_000, min(int(max_chars or 20_000), 50_000))
    request = Request(
        requested_url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
    )
    opener = build_opener(SafeRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            final_allowed, final_reason = public_url(final_url)
            if not final_allowed:
                return {"ok": False, "url": requested_url, "error": f"unsafe final URL: {final_reason}"}
            content_type = response.headers.get_content_type()
            if content_type not in SUPPORTED_CONTENT_TYPES:
                return {
                    "ok": False,
                    "url": final_url,
                    "error": f"unsupported content type: {content_type}",
                }
            charset = response.headers.get_content_charset() or "utf-8"
            content_encoding = str(response.headers.get("Content-Encoding") or "").strip().lower()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(getattr(response, "status", None) or response.getcode() or 200)
        byte_truncated = len(raw) > MAX_RESPONSE_BYTES
        raw = raw[:MAX_RESPONSE_BYTES]
        if content_encoding == "gzip" or raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_RESPONSE_BYTES + 1)
        elif content_encoding == "deflate":
            raw = zlib.decompressobj().decompress(raw, MAX_RESPONSE_BYTES + 1)
        elif content_encoding not in {"", "identity"}:
            return {
                "ok": False,
                "url": final_url,
                "error": f"unsupported content encoding: {content_encoding}",
            }
        byte_truncated = byte_truncated or len(raw) > MAX_RESPONSE_BYTES
        raw = raw[:MAX_RESPONSE_BYTES]
        decoded = raw.decode(charset, errors="replace")
        title_match = _TITLE.search(decoded) if content_type in {"text/html", "application/xhtml+xml"} else None
        title = clean_text(title_match.group(1)) if title_match else ""
        text = html_to_text(decoded) if content_type in {"text/html", "application/xhtml+xml"} else decoded.strip()
        content_truncated = len(text) > limit
        content = text[:limit]
        return {
            "ok": True,
            "requested_url": requested_url,
            "url": final_url,
            "title": title,
            "status": status,
            "content_type": content_type,
            "retrieved_at": utc_now(),
            "content": content,
            "chars": len(content),
            "word_count": len(re.findall(r"\S+", content)),
            "truncated": byte_truncated or content_truncated,
        }
    except Exception as error:
        return {"ok": False, "url": requested_url, "error": f"fetch failed: {error}"}


def fetch_public_urls(
    urls,
    max_chars_per_url: int = 12_000,
    total_max_chars: int = 40_000,
) -> dict:
    """Fetch a bounded list of sources and preserve a stable citation mapping."""

    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, (list, tuple)):
        return {"ok": False, "error": "urls must be an array", "sources": []}
    unique = []
    for value in urls:
        url = str(value or "").strip()
        if url and url not in unique:
            unique.append(url)
        if len(unique) >= 6:
            break
    if not unique:
        return {"ok": False, "error": "urls is empty", "sources": []}
    per_source = max(1_000, min(int(max_chars_per_url or 12_000), 30_000))
    total_limit = max(2_000, min(int(total_max_chars or 40_000), 100_000))
    remaining = total_limit
    sources = []
    for index, url in enumerate(unique, 1):
        if remaining <= 0:
            break
        result = fetch_public_url(url, max_chars=min(per_source, remaining))
        result["id"] = f"S{index}"
        sources.append(result)
        remaining -= len(str(result.get("content") or ""))
    return {
        "ok": any(source.get("ok") for source in sources),
        "retrieved_at": utc_now(),
        "sources": sources,
        "requested": len(unique),
        "fetched": sum(bool(source.get("ok")) for source in sources),
        "total_chars": sum(len(str(source.get("content") or "")) for source in sources),
        "truncated_by_total_limit": len(sources) < len(unique) or remaining <= 0,
        "citation_hint": "Cite each factual claim with the matching source URL; ids are stable only within this result.",
    }
