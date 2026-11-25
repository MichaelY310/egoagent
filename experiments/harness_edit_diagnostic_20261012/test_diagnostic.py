"""Infrastructure checks only. These synthetic strings are NOT research tasks."""
import json
from pathlib import Path
import tempfile
import unittest

from replay import adaptive_scope, comp, parse_junit


class DiagnosticInfrastructureTests(unittest.TestCase):
    def test_scope_does_not_invent_changed_components(self):
        scope, _ = adaptive_scope({"src/minisweagent/agents/a.py": "from minisweagent import Model\n"}, "agents")
        self.assertEqual(scope, ["agents"])

    def test_protocol_reference_links_real_changed_components(self):
        scope, _ = adaptive_scope({"src/minisweagent/agents/a.py": "from minisweagent import Model\ndef run(model: Model): pass", "src/minisweagent/models/b.py": "class M: pass"}, "agents")
        self.assertEqual(scope, ["agents", "models"])

    def test_junit_collection_error_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.xml"
            path.write_text('<testsuites><testsuite><testcase classname="a" name="b"><error message="missing symbol"/></testcase></testsuite></testsuites>')
            self.assertEqual(parse_junit(path)["counts"]["error"], 1)

    def test_existing_directory_boundaries(self):
        self.assertEqual(comp("src/minisweagent/models/utils/actions.py"), "models")
        self.assertEqual(comp("src/minisweagent/__init__.py"), "core")
        self.assertEqual(comp("src/minisweagent/config/mini.yaml"), "config")

    def test_complete_frozen_matrices_and_reproducible_scopes(self):
        manifest = json.loads((Path(__file__).parent / "results/replay_manifest.json").read_text())
        self.assertEqual(len(manifest["cases"]), 12)
        for case in manifest["cases"]:
            self.assertEqual(len(case["cells"]), 2 ** len(case["components_all_production"]))
            child = Path(__file__).parent / case["cells"][-1]["tree"]
            sources = {p: (child / p).read_text(encoding="utf-8") if (child / p).exists() else "" for p in case["production_paths"]}
            scope, _ = adaptive_scope(sources, case["seed"])
            self.assertEqual(scope, case["scopes"]["adaptive_static"])


if __name__ == "__main__":
    unittest.main()
