from __future__ import annotations

import json
import gzip
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web_access
from agent import Agent


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://example.com/final",
        content_type: str = "text/html",
        content_encoding: str = "",
    ):
        self.body = body
        self.url = url
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = f"{content_type}; charset=utf-8"
        if content_encoding:
            self.headers["Content-Encoding"] = content_encoding

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout=0):
        self.timeout = timeout
        return self.response


class WebAccessTests(unittest.TestCase):
    def test_search_query_supports_domain_exclusion_and_freshness(self):
        query = web_access.build_search_query(
            "Python release",
            domains=["https://docs.python.org/", "python.org"],
            exclude_domains=["example.com"],
            freshness="2026-01-02",
        )
        self.assertIn("site:docs.python.org", query)
        self.assertIn("site:python.org", query)
        self.assertIn("-site:example.com", query)
        self.assertIn("after:2026-01-02", query)

    def test_search_results_are_deduplicated_and_citation_ready(self):
        raw = [
            {"title": "One", "url": "https://example.com/a#part", "snippet": "A", "provider": "test"},
            {"title": "Duplicate", "url": "https://example.com/a", "snippet": "B", "provider": "test"},
            {"title": "Two", "url": "https://docs.example.org/b", "snippet": "C", "provider": "test"},
        ]
        with mock.patch.object(web_access, "_search_bing_rss", return_value=raw):
            result = web_access.search_public_web("query", max_results=5)
        self.assertTrue(result["ok"])
        self.assertEqual([item["id"] for item in result["results"]], ["S1", "S2"])
        self.assertEqual(result["results"][0]["url"], "https://example.com/a")
        self.assertEqual(result["results"][1]["domain"], "docs.example.org")
        self.assertIn("retrieved_at", result)

    def test_domain_filter_is_enforced_on_provider_results(self):
        raw = [
            {"title": "Official", "url": "https://docs.python.org/3/", "snippet": "A", "provider": "test"},
            {"title": "Noise", "url": "https://unrelated.example/python", "snippet": "B", "provider": "test"},
        ]
        with mock.patch.object(web_access, "_search_bing_rss", return_value=raw):
            result = web_access.search_public_web("Python", domains=["python.org"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["domain"], "docs.python.org")

    def test_search_falls_back_without_hiding_provider_warning(self):
        fallback = [{"title": "Fallback", "url": "https://example.com", "snippet": "ok", "provider": "ddg"}]
        with mock.patch.object(web_access, "_search_bing_rss", side_effect=RuntimeError("offline")), mock.patch.object(
            web_access, "_search_duckduckgo", return_value=fallback
        ):
            result = web_access.search_public_web("query")
        self.assertTrue(result["ok"])
        self.assertIn("Bing RSS", result["provider_warnings"][0])

    def test_public_url_blocks_private_resolution_and_url_credentials(self):
        with mock.patch.object(web_access.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
            allowed, reason = web_access.public_url("http://example.com")
        self.assertFalse(allowed)
        self.assertIn("private", reason)
        allowed, reason = web_access.public_url("https://user:pass@example.com")
        self.assertFalse(allowed)
        self.assertIn("credentials", reason)

    def test_redirect_handler_revalidates_before_following(self):
        request = mock.Mock(full_url="https://public.example/start")
        with mock.patch.object(web_access, "public_url", return_value=(False, "private target")):
            with self.assertRaises(HTTPError) as raised:
                web_access.SafeRedirectHandler().redirect_request(
                    request, None, 302, "Found", Message(), "http://127.0.0.1/admin"
                )
        self.assertIn("unsafe redirect blocked", str(raised.exception))

    def test_fetch_extracts_metadata_and_marks_truncation(self):
        response = _Response(b"<html><title>Example</title><main>Hello <b>world</b></main></html>")
        with mock.patch.object(web_access, "public_url", return_value=(True, "")), mock.patch.object(
            web_access, "build_opener", return_value=_Opener(response)
        ):
            result = web_access.fetch_public_url("https://example.com", max_chars=1000)
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "Example")
        self.assertIn("Hello world", result["content"])
        self.assertEqual(result["url"], "https://example.com/final")
        self.assertFalse(result["truncated"])

    def test_fetch_decodes_gzip_content(self):
        body = gzip.compress(b"<html><title>Compressed</title><main>Readable evidence</main></html>")
        response = _Response(body, content_encoding="gzip")
        with mock.patch.object(web_access, "public_url", return_value=(True, "")), mock.patch.object(
            web_access, "build_opener", return_value=_Opener(response)
        ):
            result = web_access.fetch_public_url("https://example.com", max_chars=1000)
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "Compressed")
        self.assertIn("Readable evidence", result["content"])

    def test_batch_fetch_assigns_ids_and_respects_total_budget(self):
        def fake_fetch(url, max_chars=0):
            return {"ok": True, "url": url, "content": "x" * max_chars}

        with mock.patch.object(web_access, "fetch_public_url", side_effect=fake_fetch):
            result = web_access.fetch_public_urls(
                ["https://one.example", "https://two.example"],
                max_chars_per_url=1500,
                total_max_chars=2200,
            )
        self.assertEqual([source["id"] for source in result["sources"]], ["S1", "S2"])
        self.assertEqual(result["total_chars"], 2200)
        self.assertTrue(result["truncated_by_total_limit"])

    def test_openmanus_keeps_web_and_browser_tools_visible_under_prompt_budget(self):
        agent = Agent(ROOT / "identity" / "openmanus", workspace=ROOT)
        visible = {tool["function"]["name"] for tool in agent.get_tools_desc()}
        for expected in ("browser", "web_search", "fetch_url", "fetch_urls", "read_file", "run_command"):
            with self.subTest(expected=expected):
                self.assertIn(expected, visible)

    def test_tool_wrappers_return_json(self):
        agent = Agent(ROOT / "identity" / "researcher", workspace=ROOT)
        tools = {agent._short_name(name): tool for name, tool in agent.tools.items()}
        self.assertIn("fetch_urls", tools)
        with mock.patch.object(web_access, "search_public_web", return_value={"ok": True, "results": []}):
            # Lazy loading imports the wrapper once; its result remains a JSON contract.
            result = tools["web_search"].func("test", _context={})
        self.assertIsInstance(json.loads(result), dict)


if __name__ == "__main__":
    unittest.main()
