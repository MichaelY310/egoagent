import unittest
import json
import tempfile
from pathlib import Path

from experiments.product_code_agent_acceptance.analyze_factorial import interaction, summarize_cell
from experiments.product_code_agent_acceptance.analyze_context_factorial import analyze as analyze_context
from experiments.product_code_agent_acceptance.analyze_team_threshold import analyze as analyze_team
from experiments.product_code_agent_acceptance.analyze_product_comparison import _elapsed


class FactorialAnalyzerTests(unittest.TestCase):
    def test_interaction_uses_lower_is_better_difference_of_differences(self):
        cells = {
            "00": {"tokens": 100.0},
            "10": {"tokens": 80.0},
            "01": {"tokens": 70.0},
            "11": {"tokens": 40.0},
        }
        self.assertEqual(interaction(cells, "tokens"), 10.0)

    def test_mechanism_evidence_must_appear_in_trace(self):
        run = {
            "status": "passed",
            "score": 1.0,
            "run_id": "run-1",
            "stats": {"tokens_actual": 10, "input_tokens_actual": 9, "cached_input_tokens_actual": 4},
            "native_trajectory": {"context_changes": [{"mode": "tool_prune"}]},
        }
        observed = summarize_cell([run], ["tool_prune"])
        missing = summarize_cell([run], ["tool_prune", "block_plan"])
        self.assertTrue(observed["mechanism_observed"])
        self.assertFalse(missing["mechanism_observed"])

    def test_context_factorial_requires_all_cells_and_recovers_memory_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            runs = []
            for memory in (0, 1):
                for pruning in (0, 1):
                    for compaction in (0, 1):
                        for repeat in (0, 1):
                            runs.append({
                                "run_id": f"{memory}{pruning}{compaction}{repeat}",
                                "flow": f"experiment_context_m{memory}_p{pruning}_c{compaction}_r{repeat}",
                                "status": "passed" if memory else "failed",
                                "score": 1.0 if memory else 0.5,
                                "stats": {"tokens_actual": 100 - 20 * pruning},
                                "event_counts": {"memory": memory},
                                "context_events": [],
                                "native_trajectory": {"component_subflows": {}},
                            })
            report_path.write_text(json.dumps({"runs": runs}), encoding="utf-8")
            result = analyze_context(report_path)
        self.assertTrue(result["design"]["complete"])
        self.assertEqual(result["primary_result"]["memory_on_passed"], 8)
        self.assertEqual(result["primary_result"]["memory_off_passed"], 0)
        self.assertEqual(result["factor_aggregates"]["tool_pruning"]["tokens_effect_on_minus_off"], -20.0)

    def test_team_threshold_pairs_single_and_team_without_calling_launch_success_benefit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tasks = root / "task_bench" / "tasks"
            tasks.mkdir(parents=True)
            runs = []
            for index, size in enumerate(("small", "medium", "large"), 1):
                task_id = f"team_threshold_{size}"
                (tasks / f"{task_id}.json").write_text(json.dumps({
                    "experiment": {"team_threshold": {"workspace_files": index, "workspace_bytes": index * 100}}
                }), encoding="utf-8")
                for arm in ("code_agent_long", "code_agent_team"):
                    runs.append({
                        "run_id": f"{size}-{arm}", "task_id": task_id, "flow": arm,
                        "status": "passed", "score": 1.0,
                        "stats": {"tokens_actual": 100 + (10 if arm.endswith("team") else 0)},
                        "native_trajectory": {"autonomous_subagents": {"worker": 1} if size == "large" and arm.endswith("team") else {}},
                    })
            report_path = root / "report.json"
            report_path.write_text(json.dumps({"runs": runs}), encoding="utf-8")
            result = analyze_team(report_path, root=root)
        self.assertTrue(result["complete"])
        self.assertEqual(result["paired_effects"][2]["team_children"], 1)
        self.assertEqual(result["paired_effects"][2]["score_delta_team_minus_single"], 0.0)

    def test_product_comparison_recovers_old_external_runner_wall_time(self):
        self.assertEqual(
            _elapsed({"stats": {}}, {"started_at": 100.25, "completed_at": 112.75}),
            12.5,
        )
        self.assertEqual(
            _elapsed({"stats": {"elapsed_seconds": 3.0}}, {"started_at": 1, "completed_at": 99}),
            3.0,
        )


if __name__ == "__main__":
    unittest.main()
