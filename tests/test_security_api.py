from __future__ import annotations

import http.client
import base64
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import harness_editor.server as server_module
from harness_editor.server import APIHandler, ThreadingHTTPServer


class LocalAPISecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), APIHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, *, headers=None, body=None):
        # Windows can abort a fresh loopback connection while the full suite is
        # rapidly creating and closing many temporary HTTP servers. Retrying a
        # transport that received no HTTP response keeps this a protocol test;
        # response status codes are never retried or hidden.
        for attempt in range(3):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                payload = response.read()
                return response.status, dict(response.getheaders()), payload
            except (ConnectionAbortedError, ConnectionResetError):
                if attempt >= 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
            finally:
                connection.close()
        raise AssertionError("unreachable")

    def test_untrusted_web_origin_cannot_read_or_mutate_runtime(self):
        status, headers, _ = self.request(
            "GET", "/api/execution/state", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        status, _, _ = self.request(
            "POST", "/api/execution/stop",
            headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
            body="{}",
        )
        self.assertEqual(status, 403)

    def test_trusted_origin_is_reflected_instead_of_wildcard(self):
        origin = "http://127.0.0.1:8880"
        status, headers, _ = self.request(
            "GET", "/api/execution/state", headers={"Origin": origin}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_originless_local_cli_request_remains_supported_without_cors(self):
        status, headers, _ = self.request("GET", "/api/execution/state")
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_mutation_requires_json_and_preflight_rejects_untrusted_origin(self):
        status, _, _ = self.request(
            "POST", "/api/execution/stop",
            headers={"Origin": "http://localhost:8880", "Content-Type": "text/plain"},
            body="{}",
        )
        self.assertEqual(status, 415)

        status, _, _ = self.request(
            "OPTIONS", "/api/execution/stop", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(status, 403)

        settings_path = "/api/security/settings?workspace=" + urllib.parse.quote(str(ROOT))
        status, _, payload = self.request(
            "POST", settings_path,
            headers={"Origin": "http://localhost:8880", "Content-Type": "application/json"},
            body="{broken",
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Malformed JSON", payload)

        status, _, payload = self.request(
            "POST", settings_path,
            headers={"Origin": "http://localhost:8880", "Content-Type": "application/json"},
            body="[]",
        )
        self.assertEqual(status, 400)
        self.assertIn(b"must be an object", payload)

    def test_approval_nonce_is_exact_single_use_and_chat_cannot_approve(self):
        handle = server_module.interactive_runs.create(ROOT)
        try:
            approval_queue = handle.input_queue
            handle.state.update({
                "running": True,
                "status": "waiting_approval",
                "waiting_for_input": True,
                "pending_approval": {"approval_id": "approval-current"},
            })
            headers = {
                "Origin": "http://127.0.0.1:8880",
                "Content-Type": "application/json",
            }

            status, _, _ = self.request(
                "POST", "/api/execution/approval", headers=headers,
                body=json.dumps({"run_id": handle.run_id, "approval_id": "approval-stale", "decision": "approved"}),
            )
            self.assertEqual(status, 409)
            self.assertTrue(approval_queue.empty())

            status, _, _ = self.request(
                "POST", "/api/execution/input", headers=headers,
                body=json.dumps({"run_id": handle.run_id, "text": "yes"}),
            )
            self.assertEqual(status, 409)
            self.assertTrue(approval_queue.empty())

            payload = json.dumps({"run_id": handle.run_id, "approval_id": "approval-current", "decision": "approved"})
            status, _, _ = self.request("POST", "/api/execution/approval", headers=headers, body=payload)
            self.assertEqual(status, 200)
            queued = handle.wait_for_approval("approval-current", lambda: False)
            self.assertEqual(queued["decision"], "approved")
            self.assertTrue(approval_queue.empty())

            status, _, _ = self.request("POST", "/api/execution/approval", headers=headers, body=payload)
            self.assertEqual(status, 409)
            self.assertTrue(approval_queue.empty())
        finally:
            handle.state["running"] = False
            server_module.interactive_runs.remove(handle.run_id)

    def test_approval_mode_route_requires_confirmation_and_preserves_other_sessions(self):
        handle = server_module.interactive_runs.create(ROOT)
        other = server_module.interactive_runs.create(ROOT)
        try:
            headers = {"Origin": "http://127.0.0.1:8880", "Content-Type": "application/json"}
            data = {"run_id": handle.run_id, "approval_mode": "auto"}
            status, _, _ = self.request("POST", "/api/execution/approval-mode", headers=headers, body=json.dumps(data))
            self.assertEqual(status, 400)
            self.assertEqual(handle.state["approval_mode"], "manual")
            data["confirmed"] = True
            status, _, _ = self.request("POST", "/api/execution/approval-mode", headers=headers, body=json.dumps(data))
            self.assertEqual(status, 200)
            self.assertEqual(handle.state["approval_mode"], "auto")
            self.assertEqual(other.state["approval_mode"], "manual")
            data["approval_mode"] = "manual"
            status, _, _ = self.request("POST", "/api/execution/approval-mode", headers=headers, body=json.dumps(data))
            self.assertEqual(status, 200)
            self.assertEqual(handle.state["approval_mode"], "manual")
        finally:
            server_module.interactive_runs.remove(handle.run_id)
            server_module.interactive_runs.remove(other.run_id)

    def test_resource_management_routes_confine_every_path_to_its_catalog(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        previous = {
            "HARNESS_DIR": server_module.HARNESS_DIR,
            "IDENTITY_DIR": server_module.IDENTITY_DIR,
            "SESSIONS_DIR": server_module.SESSIONS_DIR,
            "ENVIRONMENT_DIR": server_module.ENVIRONMENT_DIR,
            "LEGACY_ENV_DIRS": list(server_module._LEGACY_ENV_DIRS),
        }
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            root = Path(directory)
            server_module.HARNESS_DIR = root / "harness"
            server_module.IDENTITY_DIR = root / "identity"
            server_module.SESSIONS_DIR = root / "sessions"
            server_module.ENVIRONMENT_DIR = root / "environment"
            server_module._LEGACY_ENV_DIRS = []
            for key in ("HARNESS_DIR", "IDENTITY_DIR", "SESSIONS_DIR", "ENVIRONMENT_DIR"):
                getattr(server_module, key).mkdir(parents=True, exist_ok=True)
            outside = root / "outside"
            outside.mkdir()
            (outside / "sentinel.txt").write_text("keep", encoding="utf-8")
            headers = {
                "Origin": "http://127.0.0.1:8880",
                "Content-Type": "application/json",
            }
            traversal = urllib.parse.quote("../outside", safe="")
            try:
                status, _, _ = self.request(
                    "PUT", f"/api/identity/{traversal}", headers=headers, body="{}"
                )
                self.assertEqual(status, 400)

                status, _, _ = self.request(
                    "PUT", f"/api/script/safe/{traversal}", headers=headers,
                    body=json.dumps({"code": "raise RuntimeError('must not be written')"}),
                )
                self.assertEqual(status, 400)

                status, _, _ = self.request(
                    "DELETE", f"/api/session/{traversal}", headers=headers
                )
                self.assertEqual(status, 400)

                encoded_outside = base64.urlsafe_b64encode(str(outside).encode()).decode()
                opaque = urllib.parse.quote(encoded_outside, safe="")
                status, _, _ = self.request(
                    "DELETE", f"/api/environment/{opaque}/tool/sentinel", headers=headers
                )
                self.assertEqual(status, 400)
                self.assertEqual((outside / "sentinel.txt").read_text(encoding="utf-8"), "keep")
            finally:
                server_module.HARNESS_DIR = previous["HARNESS_DIR"]
                server_module.IDENTITY_DIR = previous["IDENTITY_DIR"]
                server_module.SESSIONS_DIR = previous["SESSIONS_DIR"]
                server_module.ENVIRONMENT_DIR = previous["ENVIRONMENT_DIR"]
                server_module._LEGACY_ENV_DIRS = previous["LEGACY_ENV_DIRS"]

    def test_registered_environment_handle_still_supports_safe_tool_crud(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        previous_environment_dir = server_module.ENVIRONMENT_DIR
        previous_legacy = list(server_module._LEGACY_ENV_DIRS)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            root = Path(directory)
            environment_root = root / "environment"
            environment_dir = environment_root / "demo"
            (environment_dir / "tools").mkdir(parents=True)
            server_module.ENVIRONMENT_DIR = environment_root
            server_module._LEGACY_ENV_DIRS = []
            encoded = base64.urlsafe_b64encode(str(environment_dir).encode()).decode()
            opaque = urllib.parse.quote(encoded, safe="")
            headers = {
                "Origin": "http://127.0.0.1:8880",
                "Content-Type": "application/json",
            }
            body = json.dumps({
                "meta": {"name": "safe_tool", "description": "test"},
                "scripts": {"safe_tool.py": "def safe_tool():\n    return 'ok'\n"},
            })
            try:
                status, _, _ = self.request(
                    "PUT", f"/api/environment/{opaque}/tool/safe_tool", headers=headers, body=body
                )
                self.assertEqual(status, 200)
                self.assertTrue((environment_dir / "tools" / "safe_tool" / "meta.json").is_file())

                status, _, _ = self.request(
                    "DELETE", f"/api/environment/{opaque}/tool/safe_tool", headers=headers
                )
                self.assertEqual(status, 200)
                self.assertFalse((environment_dir / "tools" / "safe_tool").exists())
            finally:
                server_module.ENVIRONMENT_DIR = previous_environment_dir
                server_module._LEGACY_ENV_DIRS = previous_legacy


if __name__ == "__main__":
    unittest.main()
