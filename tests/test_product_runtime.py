import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from harness_editor import model_router
from product_runtime import (
    ProductRuntimeError,
    apply_local_update,
    configure_provider,
    create_diagnostics_bundle,
    list_rollbacks,
    load_product_settings,
    product_diagnostics,
    rollback_update,
    save_product_settings,
)


class ProductRuntimeTests(unittest.TestCase):
    def test_settings_proxy_offline_and_privacy_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = save_product_settings(root, {
                "offline_mode": True,
                "proxy": {"https": "http://127.0.0.1:7890"},
                "mirrors": {"npm_registry": "https://registry.npmmirror.com"},
                "privacy": {"telemetry": False},
            })
            self.assertTrue(settings["offline_mode"])
            self.assertEqual(load_product_settings(root)["proxy"]["https"], "http://127.0.0.1:7890")
            self.assertEqual(os.environ["EGOAGENT_OFFLINE"], "1")
            with self.assertRaisesRegex(ProductRuntimeError, "must start"):
                save_product_settings(root, {"proxy": {"http": "127.0.0.1:7890"}})

    def test_provider_wizard_stores_secret_only_in_gitignored_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_router.configure_profile_store(root / "model-profiles.json")
            secret = "sk-test-not-a-real-secret-123456"
            result = configure_provider(root, {
                "provider": "deepseek", "model": "deepseek-test", "api_key": secret,
                "roles": ["chat", "evolver"],
            })
            self.assertTrue(result["configured"])
            self.assertNotIn(secret, json.dumps(result))
            self.assertIn(secret, (root / ".env.local").read_text(encoding="utf-8"))
            self.assertNotIn(secret, (root / "model-profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(model_router.get_role_assignments()["evolver"][0], result["profile"]["id"])

    def test_offline_router_excludes_remote_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_router.configure_profile_store(root / "models.json")
            remote = model_router.upsert_model_profile({
                "id": "remote", "name": "remote", "provider": "deepseek", "base_url": "https://api.deepseek.com",
                "model": "remote", "api_key_env": "TEST_REMOTE_KEY", "enabled": True, "priority": 100, "roles": ["chat"],
            })
            local = model_router.upsert_model_profile({
                "id": "local", "name": "local", "provider": "ollama", "base_url": "http://127.0.0.1:11434/v1",
                "model": "local", "api_key_env": "", "enabled": True, "priority": 1, "roles": ["chat"],
            })
            os.environ["TEST_REMOTE_KEY"] = "test-key"
            model_router.assign_model_role("chat", [remote["id"], local["id"]])
            previous = os.environ.get("EGOAGENT_OFFLINE")
            try:
                os.environ["EGOAGENT_OFFLINE"] = "1"
                self.assertEqual(model_router.route_model("chat")["id"], "local")
            finally:
                if previous is None:
                    os.environ.pop("EGOAGENT_OFFLINE", None)
                else:
                    os.environ["EGOAGENT_OFFLINE"] = previous
                os.environ.pop("TEST_REMOTE_KEY", None)

    def test_diagnostics_bundle_redacts_environment_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "void-web" / "out").mkdir(parents=True)
            (root / "void-web" / "out" / "server-main.js").write_text("", encoding="utf-8")
            logs = root / ".runtime-logs"
            logs.mkdir()
            secret = "sk-sensitive-diagnostics-123456789"
            os.environ["DIAGNOSTIC_TEST_API_KEY"] = secret
            (logs / "app.log").write_text(f"request authorization={secret}", encoding="utf-8")
            try:
                report = product_diagnostics(root)
                self.assertIn("checks", report)
                bundle = create_diagnostics_bundle(root)
                with zipfile.ZipFile(bundle) as archive:
                    all_text = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist())
                self.assertNotIn(secret, all_text)
                self.assertIn("[REDACTED]", all_text)
            finally:
                os.environ.pop("DIAGNOSTIC_TEST_API_KEY", None)

    def test_local_update_is_transactional_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("old", encoding="utf-8")
            update = root / "release.zip"
            with zipfile.ZipFile(update, "w") as archive:
                archive.writestr(".egoagent-update.json", json.dumps({"format": "ego.update.v1", "version": "2.0.0"}))
                archive.writestr("a.txt", "new")
                archive.writestr("nested/b.txt", "created")
            applied = apply_local_update(root, update)
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "new")
            self.assertTrue((root / "nested" / "b.txt").is_file())
            self.assertEqual(len(list_rollbacks(root)), 1)
            restored = rollback_update(root, applied["rollback_id"])
            self.assertTrue(restored["rolled_back"])
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((root / "nested" / "b.txt").exists())

    def test_update_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            update = root / "bad.zip"
            with zipfile.ZipFile(update, "w") as archive:
                archive.writestr(".egoagent-update.json", json.dumps({"format": "ego.update.v1"}))
                archive.writestr("../escape.txt", "bad")
            with self.assertRaisesRegex(ProductRuntimeError, "Unsafe"):
                apply_local_update(root, update)
            self.assertFalse((root.parent / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
