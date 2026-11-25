import os
import unittest
from unittest.mock import patch

import requests

from llm.connection_config import resolve_connection
from llm.custom_llm import CustomLLM


GLOBAL = {
    "EGOAGENT_LLM_BASE_URL": "https://api.deepseek.com",
    "EGOAGENT_LLM_MODEL": "deepseek-v4-flash",
    "EGOAGENT_LLM_API_KEY": "test-global-key",
    "DEEPSEEK_API_KEY": "test-deepseek-key",
    "SILICONFLOW_API_KEY": "test-siliconflow-key",
}
CUSTOM = {"base_url": "http://[fdbd:dc05:10:10a::27]:9638/v1", "model": "identity-model"}


class ModelConnectionConfigTests(unittest.TestCase):
    def test_explicit_identity_url_and_model_override_global(self):
        resolved = resolve_connection(CUSTOM, GLOBAL)
        self.assertEqual(resolved["base_url"], CUSTOM["base_url"])
        self.assertEqual(resolved["model"], CUSTOM["model"])
        self.assertEqual(resolved["api_key"], "")

    def test_missing_empty_null_and_whitespace_fields_inherit_global(self):
        for config in ({}, {"base_url": "", "model": ""}, {"base_url": None, "model": None},
                       {"base_url": "  ", "model": "\t\n"}):
            with self.subTest(config=config):
                resolved = resolve_connection(config, GLOBAL)
                self.assertEqual(resolved, {"base_url": GLOBAL["EGOAGENT_LLM_BASE_URL"],
                                           "model": GLOBAL["EGOAGENT_LLM_MODEL"], "api_key": GLOBAL["EGOAGENT_LLM_API_KEY"]})

    def test_only_blank_field_inherits(self):
        url_only = resolve_connection({"base_url": CUSTOM["base_url"]}, GLOBAL)
        self.assertEqual(url_only["base_url"], CUSTOM["base_url"])
        self.assertEqual(url_only["model"], GLOBAL["EGOAGENT_LLM_MODEL"])
        model_only = resolve_connection({"model": CUSTOM["model"]}, GLOBAL)
        self.assertEqual(model_only["base_url"], GLOBAL["EGOAGENT_LLM_BASE_URL"])
        self.assertEqual(model_only["model"], CUSTOM["model"])

    def test_routed_profile_is_not_overridden_either(self):
        config = {**CUSTOM, "selection": {"role": "chat"}, "api_key": "profile-key"}
        self.assertEqual(resolve_connection(config, GLOBAL), {**CUSTOM, "api_key": "profile-key"})

    def test_provider_key_only_global_configuration_still_works(self):
        ds = resolve_connection({}, {"DEEPSEEK_API_KEY": "ds"})
        self.assertEqual(ds, {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "api_key": "ds"})
        sf = resolve_connection({}, {"SILICONFLOW_API_KEY": "sf"})
        self.assertEqual(sf, {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen3-8B", "api_key": "sf"})

    def test_provider_key_matches_actual_endpoint_not_whichever_key_exists_first(self):
        resolved = resolve_connection({"base_url": "https://api.siliconflow.cn/v1", "model": "qwen"}, GLOBAL)
        self.assertEqual(resolved["api_key"], GLOBAL["SILICONFLOW_API_KEY"])

    def test_explicit_env_secret_and_inline_secret_take_priority(self):
        env = {**GLOBAL, "MY_CUSTOM_MODEL_KEY": "custom-secret"}
        self.assertEqual(resolve_connection({**CUSTOM, "api_key_env": "MY_CUSTOM_MODEL_KEY"}, env)["api_key"], "custom-secret")
        self.assertEqual(resolve_connection({**CUSTOM, "api_key": "explicit"}, env)["api_key"], "explicit")

    def test_missing_explicit_secret_is_an_error_not_a_silent_global_fallback(self):
        with self.assertRaisesRegex(ValueError, "MY_MISSING_KEY"):
            resolve_connection({"api_key_env": "MY_MISSING_KEY"}, GLOBAL)

    def test_unknown_keyless_server_never_receives_global_cloud_credentials(self):
        for url in ("http://127.0.0.1:11434/v1", CUSTOM["base_url"], "https://api.deepseek.com.attacker.invalid",
                    "http://api.deepseek.com", "https://api.deepseek.com:9443", "https://api.siliconflow.cn.attacker.invalid"):
            with self.subTest(url=url):
                self.assertEqual(resolve_connection({"base_url": url, "model": "custom"}, GLOBAL)["api_key"], "")

    def test_explicit_same_provider_can_reuse_global_credentials(self):
        resolved = resolve_connection({"base_url": " https://API.DEEPSEEK.COM:443/v1/ ", "model": " chosen "}, GLOBAL)
        self.assertEqual(resolved["api_key"], GLOBAL["EGOAGENT_LLM_API_KEY"])
        self.assertEqual(resolved["model"], "chosen")

    def test_unconfigured_fields_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "base_url"):
            resolve_connection({}, {})
        with self.assertRaisesRegex(ValueError, "model"):
            resolve_connection({"base_url": CUSTOM["base_url"]}, {"DEEPSEEK_API_KEY": "ds"})

    def test_does_not_modify_identity_or_environment(self):
        config, env = dict(CUSTOM), dict(GLOBAL)
        resolve_connection(config, env)
        self.assertEqual(config, CUSTOM)
        self.assertEqual(env, GLOBAL)

    def test_custom_llm_uses_selected_endpoint_without_cross_provider_retry(self):
        with patch.dict(os.environ, GLOBAL, clear=True), patch("llm.custom_llm.requests.post") as post:
            post.side_effect = requests.ConnectionError("test endpoint is unavailable")
            llm = CustomLLM({**CUSTOM, "max_retries": 0})
            with self.assertRaises(requests.ConnectionError):
                llm.chat([{"role": "user", "content": "test"}])
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0], CUSTOM["base_url"] + "/chat/completions")
            self.assertEqual(post.call_args.kwargs["json"]["model"], CUSTOM["model"])
            self.assertNotIn(GLOBAL["EGOAGENT_LLM_API_KEY"], str(post.call_args.kwargs["headers"]))

    def test_cleared_identity_uses_global_in_actual_client(self):
        with patch.dict(os.environ, GLOBAL, clear=True):
            llm = CustomLLM({"base_url": "", "model": ""})
            self.assertEqual(llm.base_url, "https://api.deepseek.com")
            self.assertEqual(llm.model, "deepseek-v4-flash")
            self.assertEqual(llm.api_key, GLOBAL["EGOAGENT_LLM_API_KEY"])


if __name__ == "__main__":
    unittest.main()
