import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_editor import model_router


class ModelRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Path(self.temp_dir.name) / "profiles.json"
        self.original_store = model_router._PROFILE_CONFIG_PATH
        model_router.configure_profile_store(self.store)
        model_router._run_budgets.clear()

    def tearDown(self):
        model_router.configure_profile_store(self.original_store)
        model_router._run_budgets.clear()
        self.temp_dir.cleanup()

    def _profile(self, profile_id, priority, **extra):
        return model_router.upsert_model_profile({
            "id": profile_id,
            "name": profile_id,
            "provider": "ollama",
            "base_url": f"http://127.0.0.1:11434/v1/{profile_id}",
            "model": profile_id,
            "api_key_env": "",
            "roles": ["chat", "edit", "autocomplete"],
            "priority": priority,
            "context_window": 100_000,
            **extra,
        })

    def test_plaintext_key_is_rejected_and_never_persisted(self):
        secret = "sk-should-never-be-written"
        with self.assertRaisesRegex(ValueError, "api_key_env"):
            model_router.upsert_model_profile({
                "id": "unsafe",
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
                "api_key": secret,
            })
        if self.store.exists():
            self.assertNotIn(secret, self.store.read_text(encoding="utf-8"))

    def test_role_assignment_context_and_budget_choose_an_eligible_profile(self):
        self._profile("expensive", 100, input_cost_per_m=100, output_cost_per_m=100)
        self._profile("cheap", 10, input_cost_per_m=0, output_cost_per_m=0)
        model_router.assign_model_role("edit", ["expensive", "cheap"])
        model_router.set_run_budget("run-1", 0.05)

        selected = model_router.route_model(
            "edit",
            context_tokens=1000,
            expected_output_tokens=1000,
            run_id="run-1",
        )

        self.assertEqual(selected["id"], "cheap")
        self.assertNotIn("api_key", selected)
        self.assertEqual(selected["selection"]["role"], "edit")

    def test_circuit_breaker_falls_back_then_recovers_after_success(self):
        self._profile("primary", 100)
        self._profile("fallback", 10)
        model_router.assign_model_role("chat", ["primary", "fallback"])
        for _ in range(3):
            model_router.report_model_result("primary", ok=False, latency_ms=10, error="boom")

        selected = model_router.route_model("chat")
        self.assertEqual(selected["id"], "fallback")
        profiles = {item["id"]: item for item in model_router.list_model_profiles()}
        self.assertGreater(profiles["primary"]["health"]["circuit_open_until"], 0)

        # A successful health probe closes the circuit immediately.
        model_router.report_model_result("primary", ok=True, latency_ms=5)
        self.assertEqual(model_router.route_model("chat")["id"], "primary")

    def test_secret_is_resolved_only_for_private_route(self):
        with patch.dict(os.environ, {"ROUTER_TEST_KEY": "top-secret-value"}, clear=False):
            model_router.upsert_model_profile({
                "id": "private",
                "name": "private",
                "provider": "openai_compatible",
                "base_url": "https://models.invalid/v1",
                "model": "tiny",
                "api_key_env": "ROUTER_TEST_KEY",
                "roles": ["chat"],
                "priority": 500,
            })
            model_router.assign_model_role("chat", ["private"])
            public = model_router.route_model("chat")
            private = model_router.route_model("chat", include_secret=True)

        self.assertTrue(public["has_api_key"])
        self.assertNotIn("api_key", public)
        self.assertEqual(private["api_key"], "top-secret-value")
        persisted = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertNotIn("top-secret-value", json.dumps(persisted))

    def test_generic_environment_profile_refreshes_stale_persisted_endpoint(self):
        stale = {
            "version": 2,
            "profiles": [{
                "id": "egoagent-default", "name": "stale", "provider": "openai_compatible",
                "base_url": "http://127.0.0.1:1", "model": "mock-model", "api_key_env": "EGOAGENT_LLM_API_KEY",
                "roles": ["chat"], "enabled": True,
            }],
            "roles": {"chat": ["egoagent-default"]},
            "health": {},
        }
        self.store.write_text(json.dumps(stale), encoding="utf-8")
        with patch.dict(os.environ, {
            "EGOAGENT_LLM_BASE_URL": "https://api.example.test/v1",
            "EGOAGENT_LLM_MODEL": "real-model",
            "EGOAGENT_LLM_API_KEY": "secret",
        }, clear=False):
            selected = model_router.route_model("chat", include_secret=True)
        self.assertEqual(selected["base_url"], "https://api.example.test/v1")
        self.assertEqual(selected["model"], "real-model")
        self.assertEqual(selected["api_key"], "secret")


if __name__ == "__main__":
    unittest.main()
