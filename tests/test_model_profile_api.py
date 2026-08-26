import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from harness_editor import server as server_module
from harness_editor.model_router import configure_profile_store


class ModelProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_profile_store(Path(self.temp_dir.name) / "model-profiles.json")
        self.httpd = server_module.ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.APIHandler
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        configure_profile_store(None)
        self.temp_dir.cleanup()

    def _request(self, method, path, body=None):
        request = urllib.request.Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def test_profile_role_preview_and_delete_round_trip(self):
        status, saved = self._request(
            "POST",
            "/api/model-profiles",
            {
                "id": "local-test",
                "name": "Local test model",
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "tiny-test",
                "api_key_env": "",
                "roles": ["chat", "edit"],
                "priority": 999,
                "context_window": 4096,
                "input_cost_per_m": 0,
                "output_cost_per_m": 0,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["id"], "local-test")
        self.assertNotIn("api_key", saved)

        status, assigned = self._request(
            "POST", "/api/model-roles", {"role": "edit", "profiles": ["local-test"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(assigned, {"role": "edit", "profiles": ["local-test"]})

        _, preview = self._request(
            "POST",
            "/api/model-route/preview",
            {"role": "edit", "context_tokens": 2000, "expected_output_tokens": 100},
        )
        self.assertEqual(preview["id"], "local-test")
        self.assertNotIn("api_key", preview)
        self.assertEqual(preview["selection"]["role"], "edit")

        _, listing = self._request("GET", "/api/model-profiles")
        profile = next(item for item in listing["profiles"] if item["id"] == "local-test")
        self.assertNotIn("api_key", profile)
        self.assertIn("edit", listing["roles"])

        status, removed = self._request("DELETE", "/api/model-profiles/local-test")
        self.assertEqual(status, 200)
        self.assertTrue(removed["removed"])

    def test_plaintext_secret_is_rejected_by_http_api(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._request(
                "POST",
                "/api/model-profiles",
                {
                    "name": "Unsafe",
                    "provider": "openai_compatible",
                    "base_url": "http://127.0.0.1:1/v1",
                    "model": "unsafe",
                    "api_key": "must-not-persist",
                },
            )
        self.assertEqual(raised.exception.code, 400)
        store = Path(self.temp_dir.name) / "model-profiles.json"
        persisted = store.read_text(encoding="utf-8") if store.exists() else ""
        self.assertNotIn("must-not-persist", persisted)


if __name__ == "__main__":
    unittest.main()
