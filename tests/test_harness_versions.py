import json
import tempfile
import unittest
from pathlib import Path

from harness_versions import (
    ensure_harness_versions,
    resolve_harness_version_dir,
    snapshot_harness_version,
)


class HarnessVersionTests(unittest.TestCase):
    def test_versions_are_immutable_runnable_directory_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            (root / "scripts").mkdir(parents=True)
            config = {"name": "demo", "pipeline": {"start": "a", "max_steps": 2, "workspace_preview": False, "nodes": {"a": {"id": "a", "op": "结束", "edges": []}}}}
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "scripts" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")

            baseline = ensure_harness_versions(root)
            first = baseline["latest"]
            first_dir, resolved = resolve_harness_version_dir(root, first)
            self.assertEqual(resolved, first)
            self.assertEqual((first_dir / "scripts" / "worker.py").read_text(), "VALUE = 1\n")

            config["description"] = "second"
            (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "scripts" / "worker.py").write_text("VALUE = 2\n", encoding="utf-8")
            second = snapshot_harness_version(root)
            self.assertTrue(second["created"])
            second_dir, _ = resolve_harness_version_dir(root, second["id"])
            self.assertEqual((first_dir / "scripts" / "worker.py").read_text(), "VALUE = 1\n")
            self.assertEqual((second_dir / "scripts" / "worker.py").read_text(), "VALUE = 2\n")

            duplicate = snapshot_harness_version(root)
            self.assertFalse(duplicate["created"])
            self.assertEqual(duplicate["id"], second["id"])

            (root / "scripts" / "worker.py").write_text("VALUE = 3\n", encoding="utf-8")
            script_only = snapshot_harness_version(root)
            self.assertTrue(script_only["created"])
            self.assertNotEqual(script_only["id"], second["id"])


if __name__ == "__main__":
    unittest.main()
