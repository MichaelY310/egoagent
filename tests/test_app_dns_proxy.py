from __future__ import annotations

import socket
import socketserver
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from llm.app_dns_proxy import (
    AppDNSConnectProxy,
    AppDNSProxyError,
    build_dns_query,
    parse_dns_a_response,
)
from llm.custom_llm import CustomLLM


ROOT = Path(__file__).resolve().parents[1]


class _UppercaseHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(4096)
            if not data:
                return
            self.request.sendall(data.upper())


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _read_header(client: socket.socket) -> bytes:
    result = bytearray()
    while b"\r\n\r\n" not in result:
        chunk = client.recv(4096)
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


class AppDNSProxyTests(unittest.TestCase):
    def test_dns_parser_extracts_a_record_and_ttl(self):
        transaction_id = 0x4A31
        query = build_dns_query("api.example.test", transaction_id)
        question = query[12:]
        answer = (
            b"\xc0\x0c"
            + struct.pack("!HHIH", 1, 1, 45, 4)
            + socket.inet_aton("203.0.113.17")
        )
        response = struct.pack("!HHHHHH", transaction_id, 0x8180, 1, 1, 0, 0) + question + answer

        self.assertEqual(parse_dns_a_response(response, transaction_id), [("203.0.113.17", 45)])
        with self.assertRaises(AppDNSProxyError):
            parse_dns_a_response(response, transaction_id + 1)

    def test_connect_proxy_tunnels_only_exact_allowed_host_and_port(self):
        upstream = _ThreadingServer(("127.0.0.1", 0), _UppercaseHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        upstream_port = upstream.server_address[1]
        proxy = AppDNSConnectProxy(
            {"allowed.test"}, lambda hostname: ["127.0.0.1"], {upstream_port}, idle_timeout=3
        )
        proxy_url = proxy.start()
        proxy_port = int(proxy_url.rsplit(":", 1)[1])
        try:
            with socket.create_connection(("127.0.0.1", proxy_port), timeout=3) as client:
                client.sendall(
                    f"CONNECT allowed.test:{upstream_port} HTTP/1.1\r\nHost: allowed.test\r\n\r\n".encode("ascii")
                )
                self.assertIn(b"200 Connection Established", _read_header(client))
                client.sendall(b"hello tunnel")
                self.assertEqual(client.recv(4096), b"HELLO TUNNEL")

            with socket.create_connection(("127.0.0.1", proxy_port), timeout=3) as client:
                client.sendall(
                    f"CONNECT forbidden.test:{upstream_port} HTTP/1.1\r\nHost: forbidden.test\r\n\r\n".encode("ascii")
                )
                self.assertIn(b"403 Forbidden", _read_header(client))

            with socket.create_connection(("127.0.0.1", proxy_port), timeout=3) as client:
                client.sendall(b"GET http://allowed.test/ HTTP/1.1\r\nHost: allowed.test\r\n\r\n")
                self.assertIn(b"405 Method Not Allowed", _read_header(client))
        finally:
            proxy.close()
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)

    def test_custom_llm_applies_proxy_only_to_provider_request(self):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        response.raise_for_status.return_value = None
        with patch("llm.custom_llm.app_dns_proxy_for_url", return_value="http://127.0.0.1:54321"), patch(
            "llm.custom_llm.requests.post", return_value=response
        ) as request:
            model = CustomLLM({
                "selection": {}, "base_url": "https://provider.example/v1", "model": "test-model",
                "api_key": "test-only", "max_retries": 0,
            })
            result = model.chat([{"role": "user", "content": "ping"}], max_tokens=4)

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(request.call_args.kwargs["proxies"], {"https": "http://127.0.0.1:54321"})

    def test_custom_llm_recovers_from_windows_socket_10013_with_scoped_proxy(self):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        response.raise_for_status.return_value = None
        blocked = requests.ConnectionError(
            "[WinError 10013] An attempt was made to access a socket in a way "
            "forbidden by its access permissions"
        )
        with patch("llm.custom_llm.app_dns_proxy_for_url", return_value=None), patch(
            "llm.custom_llm.ensure_app_dns_proxy", return_value="http://127.0.0.1:55443"
        ) as ensure_proxy, patch(
            "llm.custom_llm.requests.post", side_effect=[blocked, response]
        ) as request:
            model = CustomLLM({
                "selection": {}, "base_url": "https://api.deepseek.com", "model": "test-model",
                "api_key": "test-only", "max_retries": 0,
            })
            result = model.chat([{"role": "user", "content": "ping"}], max_tokens=4)

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        ensure_proxy.assert_called_once_with("api.deepseek.com")
        self.assertIsNone(request.call_args_list[0].kwargs["proxies"])
        self.assertEqual(
            request.call_args_list[1].kwargs["proxies"],
            {"https": "http://127.0.0.1:55443"},
        )


if __name__ == "__main__":
    unittest.main()
