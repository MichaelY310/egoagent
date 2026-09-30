import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "experiments" / "real_layer_evolution" / "run_harnessbench_pilot.py"
SPEC = importlib.util.spec_from_file_location("real_layer_evolution_pilot", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RealLayerEvolutionTests(unittest.TestCase):
    def test_family_split_is_distinct(self):
        for family in MODULE.FAMILIES.values():
            self.assertNotEqual(family.validation_task, family.heldout_task)

    def test_skill_is_answer_free_and_reads_public_help(self):
        protocol = {
            "title": "Use logq safely",
            "description": "Inspect an unfamiliar logq interface before operating it.",
            "knowledge": "Read the help instead of guessing flags.",
            "procedure": ["Invoke --help", "Use the required output mode"],
            "failure_modes": ["Do not guess percentile semantics"],
            "harness_preflight": "Inspect the tool help before acting.",
            "authoring_metadata": {"tool_help_sha256": "abc"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            identity = Path(temporary) / "identity"
            (identity / "ego" / "skills").mkdir(parents=True)
            MODULE._materialize_skill(identity, MODULE.FAMILIES["logq"], protocol)
            source = next((identity / "ego" / "skills").rglob("*.py")).read_text(encoding="utf-8")
            self.assertIn('"--help"', source)
            self.assertNotIn("task_373_cli_logq_mean_by_component", source)

    def test_protocol_rejects_heldout_leakage_contract(self):
        family = MODULE.FAMILIES["logq"]
        self.assertNotIn(family.heldout_task, family.validation_task)

    def test_candidate_has_two_independent_evidence_lineages(self):
        row = {
            "task_id": "external",
            "repetition": 1,
            "split": "validation",
            "static": {"success": 0.0, "tokens": 10, "status": "failed"},
            "knowledge": {"success": 1.0, "tokens": 8, "status": "passed"},
        }
        candidate = MODULE._candidate_measurements("knowledge", [row])
        self.assertEqual(
            {item["lineage_id"] for item in candidate["evidence"]},
            {"validation-task-family", "heldout-original-verifier"},
        )

    def test_static_candidate_is_explicit_noop(self):
        rows = [
            {
                "task_id": "validation",
                "repetition": 1,
                "split": "validation",
                "static": {"success": 1.0, "tokens": 10, "status": "passed"},
            },
            {
                "task_id": "heldout",
                "repetition": 1,
                "split": "heldout",
                "static": {"success": 1.0, "tokens": 12, "status": "passed"},
            },
        ]
        candidate = MODULE._candidate_measurements(MODULE.CONTROL, rows)
        self.assertEqual(candidate["kind"], "none")

    def test_fixture_relocates_cli_invocation_log(self):
        # Exercise the adapter without requiring an untracked benchmark clone.
        # This is an import/relocation test, not a benchmark effectiveness claim.
        def setup(workspace):
            tool = workspace / "tools" / "logq"
            tool.parent.mkdir()
            log = repr(str((workspace / ".hb_tool_calls").resolve()))
            tool.write_text(f"with open({log}, 'a') as log:\n    log.write('called')\n", encoding="utf-8")
            tool.chmod(0o755)

        task = SimpleNamespace(setup=setup)
        files = MODULE._embedded_files(task)
        value = files["tools/logq"]
        source = value["content"] if isinstance(value, dict) else value
        self.assertIn("with open('.hb_tool_calls'", source)
        self.assertNotIn("ego_realbench_fixture_", source)

    def test_harness_keeps_structured_task_context(self):
        protocol = {
            "title": "Use logq safely",
            "description": "Inspect an unfamiliar logq interface before operating it.",
            "knowledge": "Read the help instead of guessing flags.",
            "procedure": ["Invoke --help"],
            "failure_modes": ["Do not guess flags"],
            "harness_preflight": "Inspect the tool help before acting.",
            "authoring_metadata": {"tool_help_sha256": "abc"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            original = MODULE.RUN_ROOT
            try:
                MODULE.RUN_ROOT = Path(temporary)
                target = MODULE._materialize_harness("unit", MODULE.FAMILIES["logq"], protocol)
                graph = json.loads((target / "config.json").read_text(encoding="utf-8"))
            finally:
                MODULE.RUN_ROOT = original
            nodes = graph["pipeline"]["nodes"]
            self.assertEqual(nodes["input"]["outputs"]["text"], "request")
            self.assertEqual(nodes["preflight"]["op"], "进程")
            self.assertEqual(nodes["preflight"]["inputs"]["cwd"], "$ctx.task.workspace")
            self.assertEqual(nodes["preflight"]["args"], ["tools/logq", "--help"])
            self.assertEqual(nodes["preflight"]["edges"][0]["condition"], "process_succeeded")

    def test_resume_cell_is_mutated_in_place_for_final_report(self):
        original = {
            "family": "logq",
            "split": "heldout",
            "task_id": "task-heldout",
            "repetition": 1,
            "harness": {"status": "error"},
        }
        rows = [original]
        row, resumed = MODULE._merge_resumed_cell(
            rows,
            family="logq",
            split="heldout",
            task_id="task-heldout",
            repetition=1,
        )
        self.assertTrue(resumed)
        row["harness"] = {"status": "passed"}
        self.assertIs(rows[0], row)
        self.assertEqual(rows[0]["harness"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
