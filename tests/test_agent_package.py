from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path

from agent_package import (
    PackageError,
    build_manifest,
    fork_package,
    inspect_package,
    install_package,
    list_installed,
    pack_package,
    uninstall_package,
    validate_manifest,
)
from package_registry import LocalPackageRegistry, version_satisfies


class AgentPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        self.source.mkdir()
        self.destination.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_component(self, kind: str, name: str, content: str) -> dict:
        relative_root = {"identity": "identity", "harness": "harness", "environment": "environment"}[kind]
        path = self.source / relative_root / name
        path.mkdir(parents=True, exist_ok=True)
        filename = "id.json" if kind == "identity" else "config.json"
        (path / filename).write_text(content, encoding="utf-8")
        return {"kind": kind, "name": name, "source": str(path.relative_to(self.source))}

    def test_signed_package_pack_inspect_install_update_and_recoverable_uninstall(self):
        component = self.make_component("identity", "demo_identity", '{"name":"v1"}')
        key = b"local-test-signing-key"
        archive = self.root / "demo.egoagentpkg"
        manifest = build_manifest("demo", "1.0.0", [component], permissions=["read"], examples=[{"prompt": "hello"}])
        packed = pack_package(manifest, self.source, archive, signing_key=key)

        inspected = inspect_package(archive, signing_key=key, require_signature=True)
        self.assertEqual(inspected["signature_status"], "verified")
        self.assertEqual(packed["files"], 1)

        installed = install_package(archive, self.destination, signing_key=key, require_signature=True)
        target = self.destination / "identity" / "demo_identity" / "id.json"
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["name"], "v1")
        self.assertEqual(len(list_installed(self.destination)), 1)

        target.write_text('{"name":"local-edit"}', encoding="utf-8")
        with self.assertRaisesRegex(PackageError, "local changes"):
            uninstall_package("demo", self.destination)
        removed = uninstall_package("demo", self.destination, force=True)
        self.assertFalse(target.exists())
        self.assertTrue(Path(removed["recoverable_from"]).exists())

    def test_update_is_transactional_and_fork_rewrites_provenance(self):
        component = self.make_component("harness", "demo_harness", '{"name":"v1"}')
        first = self.root / "first.egoagentpkg"
        pack_package(build_manifest("harness-pack", "1.0.0", [component]), self.source, first)
        install_package(first, self.destination)

        (self.source / "harness" / "demo_harness" / "config.json").write_text('{"name":"v2"}', encoding="utf-8")
        second = self.root / "second.egoagentpkg"
        pack_package(build_manifest("harness-pack", "1.1.0", [component]), self.source, second)
        updated = install_package(second, self.destination, allow_update=True)
        self.assertEqual(json.loads((self.destination / "harness" / "demo_harness" / "config.json").read_text())["name"], "v2")
        self.assertTrue(Path(updated["installed"]["backup"]).exists())

        forked_path = self.root / "forked.egoagentpkg"
        forked = fork_package(second, forked_path, "harness-fork", "0.1.0")
        self.assertEqual(forked["manifest"]["package"]["name"], "harness-fork")
        self.assertEqual(forked["manifest"]["provenance"]["forked_from"]["name"], "harness-pack")

    def test_file_task_component_installs_as_a_file(self):
        task = self.source / "task.json"
        task.write_text('{"version":"ego.task.v1","id":"pack-task"}', encoding="utf-8")
        manifest = build_manifest("task-pack", "1.0.0", [{"kind": "task", "name": "pack-task.json", "source": "task.json"}])
        archive = self.root / "task.egoagentpkg"
        pack_package(manifest, self.source, archive)
        install_package(archive, self.destination)
        self.assertTrue((self.destination / "task_bench" / "tasks" / "pack-task.json").is_file())

    def test_manifest_rejects_plaintext_secrets_and_archive_traversal(self):
        manifest = build_manifest("safe", "1.0.0", [{"kind": "identity", "name": "safe", "source": "identity/safe"}])
        manifest["provenance"]["api_key"] = "secret-value"
        with self.assertRaisesRegex(PackageError, "plaintext secret"):
            validate_manifest(manifest)

        malicious = self.root / "malicious.egoagentpkg"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape", "bad")
            archive.writestr("manifest.json", "{}")
        with self.assertRaisesRegex(PackageError, "unsafe package path"):
            inspect_package(malicious)


class LocalRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.install_root = self.root / "install"
        self.source.mkdir()
        self.install_root.mkdir()
        self.registry = LocalPackageRegistry(self.root / "registry")
        self.key = self.registry.signing_key(create=True)

    def tearDown(self):
        self.temp.cleanup()

    def package(self, package_name: str, component_name: str, dependencies=None) -> Path:
        component = self.source / package_name / component_name
        component.mkdir(parents=True)
        (component / "id.json").write_text(json.dumps({"name": component_name}), encoding="utf-8")
        archive = self.root / f"{package_name}.egoagentpkg"
        manifest = build_manifest(
            package_name, "1.0.0",
            [{"kind": "identity", "name": component_name, "source": str(component.relative_to(self.source))}],
            dependencies=dependencies,
        )
        pack_package(manifest, self.source, archive, signing_key=self.key)
        return archive

    def test_registry_resolves_dependencies_trust_search_ratings_and_install(self):
        base = self.package("base-pack", "base_identity")
        app = self.package("app-pack", "app_identity", {"base-pack": "^1.0.0"})
        self.registry.add(base, trust="verified")
        self.registry.add(app, trust="verified")

        order = self.registry.dependency_order("app-pack")
        self.assertEqual([item["name"] for item in order], ["base-pack", "app-pack"])
        result = self.registry.install("app-pack", self.install_root)
        self.assertEqual([item["name"] for item in result["installed"]], ["base-pack", "app-pack"])
        self.assertTrue((self.install_root / "identity" / "base_identity" / "id.json").is_file())
        self.assertEqual(self.registry.rate("app-pack", "1.0.0", "tester", 5, "works")["average"], 5.0)
        self.assertEqual(self.registry.search("app_identity")[0]["name"], "app-pack")

    def test_untrusted_install_requires_explicit_override(self):
        archive = self.package("untrusted-pack", "untrusted_identity")
        self.registry.add(archive, trust="untrusted")
        with self.assertRaisesRegex(PackageError, "untrusted"):
            self.registry.install("untrusted-pack", self.install_root)
        self.registry.install("untrusted-pack", self.install_root, allow_untrusted=True)

    def test_semver_constraints(self):
        self.assertTrue(version_satisfies("1.4.2", "^1.2.0"))
        self.assertFalse(version_satisfies("2.0.0", "^1.2.0"))
        self.assertTrue(version_satisfies("0.3.5", ">=0.3.0"))

    def test_http_package_workflow_packs_lists_installs_and_uninstalls(self):
        from harness_editor import server as server_module

        identity = self.install_root / "identity" / "http_identity"
        identity.mkdir(parents=True)
        (identity / "id.json").write_text('{"name":"http"}', encoding="utf-8")
        previous_root = server_module._PROJECT_ROOT_FOR_IMPORTS
        previous_registry = server_module._package_registry
        server_module._PROJECT_ROOT_FOR_IMPORTS = self.install_root
        server_module._package_registry = LocalPackageRegistry(self.install_root / ".egoagent" / "registry")
        httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.APIHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(path, payload):
            request = urllib.request.Request(
                base + path, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())

        try:
            status, packed = post("/api/packages/pack", {
                "name": "http-pack", "version": "1.0.0", "description": "HTTP test",
                "components": [{"kind": "identity", "name": "http_identity"}],
                "permissions": ["read"], "sign": True, "trust": "verified",
            })
            self.assertEqual(status, 201)
            self.assertTrue(Path(packed["path"]).is_file())
            with urllib.request.urlopen(base + "/api/packages?query=http-pack", timeout=5) as response:
                catalog = json.loads(response.read())
            self.assertEqual(catalog["packages"][0]["name"], "http-pack")

            # Simulate the receiving repository not yet having the component.
            import shutil
            shutil.rmtree(identity)
            status, installed = post("/api/packages/install", {"name": "http-pack", "version": "1.0.0"})
            self.assertEqual(status, 200)
            self.assertTrue(installed["ok"])
            self.assertTrue((identity / "id.json").is_file())
            status, removed = post("/api/packages/uninstall", {"name": "http-pack"})
            self.assertEqual(status, 200)
            self.assertTrue(removed["ok"])
        finally:
            httpd.shutdown(); httpd.server_close(); thread.join(timeout=2)
            server_module._PROJECT_ROOT_FOR_IMPORTS = previous_root
            server_module._package_registry = previous_registry


if __name__ == "__main__":
    unittest.main()
