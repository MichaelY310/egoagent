import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness_blueprint import HarnessBlueprintService
from pipeline_schema import validate_pipeline
from task_bench.engine import load_task_specs


ROOT = Path(__file__).resolve().parents[1]


class VideoEvolutionDemoTests(unittest.TestCase):
    def _copy_fixture(self, temporary: Path, name: str) -> HarnessBlueprintService:
        target = temporary / "harness" / name
        target.mkdir(parents=True)
        shutil.copy2(ROOT / "harness" / name / "config.json", target / "config.json")
        return HarnessBlueprintService(temporary)

    def test_all_recording_harnesses_are_valid_runtime_flows(self):
        for name in ("flow_evolution_showcase", "demo_fragile_release_flow", "demo_noisy_research_flow"):
            with self.subTest(name=name):
                config = json.loads((ROOT / "harness" / name / "config.json").read_text(encoding="utf-8"))
                self.assertEqual(validate_pipeline(config["pipeline"]), [])

    def test_safety_demo_can_add_an_approval_boundary_transactionally(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._copy_fixture(Path(tmp), "demo_fragile_release_flow")
            before = service.load("demo_fragile_release_flow")
            result = service.patch(
                "demo_fragile_release_flow",
                [
                    {
                        "op": "add_step",
                        "after": "plan",
                        "step": {
                            "id": "approve_execution",
                            "type": "approval",
                            "routes": [
                                {"condition": "approved", "to": "execute"},
                                {"condition": "rejected", "to": "done"},
                            ],
                            "config": {
                                "prompt_text": "Approve this release plan?",
                                "data": "$ctx.plan",
                                "default": "rejected",
                            },
                        },
                    },
                    {"op": "connect", "from": "plan", "condition": "text", "to": "approve_execution"},
                ],
                expected_revision=before["revision"],
                reason="measured cancellations require an execution boundary",
            )
            nodes = result["config"]["pipeline"]["nodes"]
            self.assertEqual(nodes["approve_execution"]["op"], "人工审批")
            self.assertEqual(nodes["plan"]["edges"][1]["to"], "approve_execution")
            self.assertTrue(result["transaction_id"])
            self.assertNotEqual(result["revision"], before["revision"])
            rolled_back = service.rollback(result["transaction_id"], expected_revision=result["revision"])
            self.assertEqual(rolled_back["revision"], before["revision"])

    def test_context_demo_can_extract_search_to_an_isolated_subflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._copy_fixture(Path(tmp), "demo_noisy_research_flow")
            before = service.load("demo_noisy_research_flow")
            result = service.patch(
                "demo_noisy_research_flow",
                [
                    {
                        "op": "add_step",
                        "after": "input",
                        "step": {
                            "id": "discover_capability",
                            "type": "subflow",
                            "routes": [{"condition": "subflow_done", "to": "worker"}],
                            "config": {
                                "harness": "component_capability_discovery",
                                "share_session": False,
                                "agent_map": {"searcher": "worker"},
                                "component_inputs": {"query": "${ctx.request}", "max_tool_rounds": 2},
                                "component_outputs": {"result": "capability_context"},
                                "result_mode": "data",
                            },
                        },
                    },
                    {"op": "connect", "from": "input", "condition": "input", "to": "discover_capability"},
                    {
                        "op": "update_step",
                        "id": "worker",
                        "changes": {
                            "config": {
                                "instructions": "Solve ${ctx.request}. Reuse this compact discovery result: ${ctx.capability_context}"
                            }
                        },
                    },
                ],
                expected_revision=before["revision"],
                reason="hide repeated catalog traces behind a result-only SubFlow",
                dry_run=True,
            )
            node = result["config"]["pipeline"]["nodes"]["discover_capability"]
            self.assertEqual(node["op"], "子流程")
            self.assertFalse(node["share_session"])
            self.assertEqual(node["harness"], "component_capability_discovery")
            self.assertEqual(result["config"]["pipeline"]["nodes"]["input"]["edges"][0]["to"], "discover_capability")

    def test_three_new_video_tasks_are_discoverable_and_use_real_evaluation_evidence(self):
        tasks = {task["id"]: task for task in load_task_specs(ROOT / "task_bench" / "tasks")}
        expected = {
            "video_agent_factory_live",
            "video_flow_safety_evolution",
            "video_subflow_extraction_evolution",
        }
        self.assertTrue(expected.issubset(tasks))
        for task_id in expected:
            checks = tasks[task_id]["evaluation"]["checks"]
            self.assertTrue(any(check["type"] == "event_emitted" for check in checks))
            self.assertTrue(tasks[task_id]["execution"]["interactive"])
            self.assertTrue(tasks[task_id]["evolution"]["allowed"])


if __name__ == "__main__":
    unittest.main()
