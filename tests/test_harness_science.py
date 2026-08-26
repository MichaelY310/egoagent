from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ego_ir import config_to_text
from harness_conformance import inspect_contract, load_manifest, run_suite
from harness_translation_benchmark import build_dataset, score_translation, vocabulary_report
from science_loop import STAGES, ScienceLoopError, ScienceRepository
from pipeline_schema import canonical_op


class HarnessConformanceTests(unittest.TestCase):
    def test_every_pinned_replica_passes_structural_contract(self):
        manifest = load_manifest()
        self.assertEqual(len(manifest["contracts"]), 15)
        report = run_suite(behavioral=False)
        self.assertEqual(report["summary"]["core_passed"], 15)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["external_blocked"], 15)
        for contract in manifest["contracts"]:
            result = inspect_contract(contract)
            self.assertTrue(result["passed"], contract["id"])
            self.assertFalse(result["graph"]["operations"] and "Python" in result["graph"]["operations"])

    def test_translation_dataset_is_real_and_roundtrips_exactly(self):
        dataset = build_dataset()
        self.assertEqual(len(dataset), 15)
        self.assertEqual({item["target"]["format"] for item in dataset}, {"EGOIR/1"})
        self.assertTrue({item["split"] for item in dataset} <= {"train", "validation", "heldout"})
        for item in dataset:
            score = score_translation(item["id"], item["target"]["text"])
            self.assertTrue(score["valid"], item["id"])
            self.assertTrue(score["contract_passed"], item["id"])
            self.assertTrue(score["exact"], item["id"])

    def test_translation_scorer_rejects_syntax_and_semantic_omissions(self):
        self.assertFalse(score_translation("aider", "not ego ir")["valid"])
        config = json.loads((ROOT / "harness" / "aider_replica" / "config.json").read_text(encoding="utf-8"))
        del config["pipeline"]["nodes"]["parse_edits"]
        for node in config["pipeline"]["nodes"].values():
            node["edges"] = [edge for edge in node.get("edges", []) if edge.get("to") != "parse_edits"]
        score = score_translation("aider", config_to_text(config))
        self.assertTrue(score["valid"])
        self.assertFalse(score["contract_passed"])

    def test_vocabulary_report_covers_all_projects(self):
        report = vocabulary_report(build_dataset())
        self.assertEqual(report["projects"], 15)
        self.assertEqual(report["uncovered_projects"], [])
        self.assertIn("循环", report["minimum_complete_operation_vocabulary"])
        self.assertIn("记忆", report["minimum_complete_operation_vocabulary"])

    def test_weak_model_camel_case_operation_aliases_are_canonical(self):
        self.assertEqual(canonical_op("Context"), "上下文")
        self.assertEqual(canonical_op("HumanApproval"), "人工审批")
        self.assertEqual(canonical_op("ToolReview"), "工具审查")


class ScienceLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.workspace = Path(self.temp.name)
        self.repo = ScienceRepository(self.workspace)
        self.project = self.repo.create("Test a falsifiable mechanism", creator="researcher", project_id="demo")
        self.paper = self.workspace / "paper.txt"
        self.paper.write_text("source snapshot", encoding="utf-8")
        self.source = self.repo.add_artifact("demo", self.paper, kind="paper", actor="researcher")["id"]
        self.code = self.workspace / "experiment.py"
        self.code.write_text("print('measurement=1')\n", encoding="utf-8")
        self.code_artifact = self.repo.add_artifact("demo", self.code, kind="code", actor="engineer")["id"]
        self.output = self.workspace / "result.txt"
        self.output.write_text("measurement=1", encoding="utf-8")
        self.output_artifact = self.repo.add_artifact("demo", self.output, kind="experiment-output", actor="runner")["id"]
        self.report = self.workspace / "report.md"
        self.report.write_text("# Verified report", encoding="utf-8")
        self.report_artifact = self.repo.add_artifact("demo", self.report, kind="report", actor="writer")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def submit_until_review(self):
        self.repo.submit_stage("demo", "retrieve", actor="researcher", payload={"evidence_refs": [self.source]})
        self.repo.submit_stage("demo", "hypothesis", actor="researcher", payload={"hypotheses": [{"id": "h1", "statement": "The mechanism changes the measurement", "falsification": "measurement remains zero", "evidence_refs": [self.source]}]})
        self.repo.submit_stage("demo", "plan", actor="researcher", payload={"experiments": [{"id": "e1", "command": ["python", "experiment.py"], "expected_observation": "non-zero measurement"}]})
        self.repo.submit_stage("demo", "implement", actor="engineer", payload={"summary": "Implemented the registered experiment", "artifact_refs": [self.code_artifact]})
        self.repo.submit_stage("demo", "execute", actor="runner", payload={"results": [{"experiment_id": "e1", "command": ["python", "experiment.py"], "exit_code": 0, "artifact_refs": [self.output_artifact]}]})
        self.repo.submit_stage("demo", "analyze", actor="analyst", payload={"claims": [{"id": "c1", "text": "The measurement is non-zero", "evidence_refs": [self.output_artifact]}]})
        self.repo.submit_stage("demo", "repair", actor="engineer", payload={"decision": "not_needed", "reason": "experiment passed"})

    def test_stage_order_and_evidence_are_enforced(self):
        with self.assertRaisesRegex(ScienceLoopError, "stage order"):
            self.repo.submit_stage("demo", "plan", actor="researcher", payload={})
        with self.assertRaisesRegex(ScienceLoopError, "unknown evidence"):
            self.repo.submit_stage("demo", "retrieve", actor="researcher", payload={"evidence_refs": ["artifact:missing"]})

    def test_independent_review_and_complete_audit(self):
        self.submit_until_review()
        with self.assertRaisesRegex(ScienceLoopError, "independent reviewer"):
            self.repo.submit_stage("demo", "independent_review", actor="researcher", payload={"approved": True, "claim_ids": ["c1"], "evidence_refs": [self.output_artifact]})
        self.repo.submit_stage("demo", "independent_review", actor="reviewer", payload={"approved": True, "claim_ids": ["c1"], "evidence_refs": [self.output_artifact]})
        state = self.repo.submit_stage("demo", "report", actor="writer", payload={"summary": "Evidence-bound result", "claim_ids": ["c1"], "artifact_refs": [self.report_artifact]})
        self.assertEqual(state["status"], "complete")
        self.assertIsNone(state["current_stage"])
        audit = self.repo.audit("demo")
        self.assertTrue(audit["passed"])
        self.assertTrue(all(audit["stage_coverage"].values()))

    def test_unplanned_or_self_reported_execution_is_rejected(self):
        self.repo.submit_stage("demo", "retrieve", actor="researcher", payload={"evidence_refs": [self.source]})
        self.repo.submit_stage("demo", "hypothesis", actor="researcher", payload={"hypotheses": [{"id": "h1", "statement": "x", "falsification": "not x", "evidence_refs": [self.source]}]})
        self.repo.submit_stage("demo", "plan", actor="researcher", payload={"experiments": [{"id": "e1", "command": ["python", "experiment.py"], "expected_observation": "x"}]})
        self.repo.submit_stage("demo", "implement", actor="engineer", payload={"summary": "implemented", "artifact_refs": [self.code_artifact]})
        with self.assertRaisesRegex(ScienceLoopError, "artifact evidence"):
            self.repo.submit_stage("demo", "execute", actor="runner", payload={"results": [{"experiment_id": "e1", "command": ["python", "experiment.py"], "exit_code": 0, "artifact_refs": []}]})

    def test_artifact_tampering_is_detected(self):
        evidence = self.repo.load("demo")["evidence"][self.source]
        stored = self.repo._project_dir("demo") / evidence["path"]
        stored.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ScienceLoopError, "integrity"):
            self.repo.load("demo")


if __name__ == "__main__":
    unittest.main()
