import json
import unittest
from pathlib import Path

from pipeline_engine import _format_prompt
from pipeline_schema import validate_component_manifest, validate_pipeline


ROOT = Path(__file__).resolve().parent.parent


class ProductCodeAgentFlowTests(unittest.TestCase):
    def test_context_curator_budget_accepts_real_multi_turn_metadata(self):
        config = json.loads((ROOT / "harness" / "component_context_curator" / "config.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(config["pipeline"]["budget"]["max_tokens"], 64000)

    def load(self, name):
        return json.loads((ROOT / "harness" / name / "config.json").read_text(encoding="utf-8"))

    def test_product_flows_are_valid_and_main_agents_cannot_bypass_tail_nodes(self):
        for name in (
            "code_agent_auto", "code_agent_fast", "code_agent_long", "code_agent_team",
            "product_adaptive_code_agent", "product_adaptive_no_evolution", "product_adaptive_no_memory",
            "product_adaptive_no_delegation", "product_adaptive_no_context_governance",
            "product_adaptive_pressure_lab", "product_adaptive_pressure_no_context", "product_core_code_agent",
            "product_adaptive_tool_pruning_on", "product_adaptive_tool_pruning_off",
            "product_adaptive_compaction_only", "product_adaptive_context_combo",
            "product_bounded_code_worker", "product_context_endurance_agent",
            "product_context_endurance_governed", "product_context_endurance_curation_only",
            "product_context_endurance_compaction_only", "product_context_endurance_ungoverned",
        ):
            config = self.load(name)
            self.assertEqual(validate_pipeline(config["pipeline"]), [], name)
            self.assertEqual(validate_component_manifest(config.get("component")), [], name)

        for name in ("product_adaptive_code_agent", "product_core_code_agent"):
            infer = self.load(name)["pipeline"]["nodes"]["infer"]
            hidden = set(infer.get("hidden_tools", []))
            self.assertTrue({"terminate", "end_session", "submit_result"} <= hidden, name)
        adaptive_context = self.load("product_adaptive_code_agent")["pipeline"]["context"]
        self.assertEqual(adaptive_context.get("_trajectory"), [])
        worker = self.load("product_bounded_code_worker")
        self.assertEqual(worker["return_mode"], "last")
        self.assertIn("create_harness", worker["pipeline"]["nodes"]["infer"]["hidden_tools"])

    def test_user_facing_code_agents_reuse_two_tested_engines(self):
        fast = self.load("code_agent_fast")
        long = self.load("code_agent_long")
        team = self.load("code_agent_team")
        auto = self.load("code_agent_auto")

        self.assertEqual(fast["pipeline"]["nodes"]["run_fast"]["harness"], "product_core_code_agent")
        self.assertEqual(long["pipeline"]["nodes"]["run_long"]["harness"], "product_adaptive_code_agent")
        self.assertEqual(auto["pipeline"]["nodes"]["run_fast"]["harness"], "product_core_code_agent")
        self.assertEqual(auto["pipeline"]["nodes"]["run_standard"]["harness"], "product_adaptive_code_agent")
        self.assertEqual(auto["pipeline"]["nodes"]["run_long"]["harness"], "product_adaptive_code_agent")
        self.assertEqual(auto["pipeline"]["nodes"]["run_team"]["harness"], "product_adaptive_code_agent")
        self.assertEqual(team["pipeline"]["nodes"]["run_team"]["harness"], "product_adaptive_code_agent")

        standard = auto["pipeline"]["nodes"]["run_standard"]["component_inputs"]
        self.assertIs(standard["enable_memory"], True)
        self.assertIs(standard["enable_compaction"], True)
        self.assertIs(standard["enable_tool_pruning"], True)
        self.assertIs(standard["enable_evolution"], False)
        self.assertIs(standard["enable_delegation"], False)
        self.assertIs(standard["enable_curation"], False)

        long_inputs = auto["pipeline"]["nodes"]["run_long"]["component_inputs"]
        self.assertIs(long_inputs["enable_evolution"], True)
        self.assertIs(long_inputs["enable_delegation"], False)
        self.assertIs(long_inputs["enable_curation"], False)
        self.assertIs(long_inputs["enable_memory"], True)
        self.assertIs(long_inputs["enable_compaction"], True)
        self.assertIs(long_inputs["enable_tool_pruning"], True)
        team_inputs = auto["pipeline"]["nodes"]["run_team"]["component_inputs"]
        self.assertIs(team_inputs["enable_evolution"], False)
        self.assertIs(team_inputs["enable_delegation"], True)
        self.assertIs(team_inputs["enable_curation"], False)
        self.assertIs(team_inputs["enable_memory"], True)
        self.assertIs(team_inputs["enable_compaction"], True)
        self.assertIs(team_inputs["enable_tool_pruning"], True)
        route_schema = auto["pipeline"]["nodes"]["route"]["output_schema"]
        self.assertEqual(route_schema["properties"]["profile"]["enum"], ["fast", "standard", "long", "team"])
        self.assertIn("/fast", auto["prompts"]["route"]["default"])
        self.assertIn("/team", auto["prompts"]["route"]["default"])
        nodes = auto["pipeline"]["nodes"]
        self.assertIn("starts_with(lower(strip(ctx.request)), '/fast')", nodes["override_fast"]["condition"])
        self.assertIn("starts_with(lower(strip(ctx.request)), '/team')", nodes["override_team"]["condition"])
        self.assertEqual(nodes["set_fast_override"]["edges"][0]["to"], "run_fast")
        self.assertEqual(nodes["set_standard_override"]["edges"][0]["to"], "run_standard")
        self.assertEqual(nodes["set_long_override"]["edges"][0]["to"], "run_long")
        self.assertEqual(nodes["set_team_override"]["edges"][0]["to"], "run_team")
        self.assertEqual(auto["catalog"]["visibility"], "public")

    def test_internal_product_engines_are_reusable_components(self):
        for name in ("product_core_code_agent", "product_adaptive_code_agent"):
            config = self.load(name)
            self.assertEqual(config["catalog"]["visibility"], "internal")
            self.assertTrue(config["component"]["share_session"])
            self.assertIn("answer", config["component"]["outputs"])

    def test_no_evolution_ablation_reuses_the_exact_product_component(self):
        node = self.load("product_adaptive_no_evolution")["pipeline"]["nodes"]["run_without_evolution"]
        self.assertEqual(node["harness"], "product_adaptive_code_agent")
        self.assertIs(node["component_inputs"]["enable_evolution"], False)

    def test_matched_ablation_switches_are_component_inputs(self):
        no_delegation = self.load("product_adaptive_no_delegation")["pipeline"]["nodes"]["run_without_delegation"]
        self.assertEqual(no_delegation["harness"], "product_adaptive_code_agent")
        self.assertIs(no_delegation["component_inputs"]["enable_delegation"], False)

        no_context = self.load("product_adaptive_no_context_governance")["pipeline"]["nodes"]["run_without_context_governance"]
        self.assertEqual(no_context["harness"], "product_adaptive_code_agent")
        self.assertIs(no_context["component_inputs"]["enable_curation"], False)
        self.assertIs(no_context["component_inputs"]["enable_compaction"], False)

        no_memory = self.load("product_adaptive_no_memory")["pipeline"]["nodes"]["run_without_memory"]
        self.assertEqual(no_memory["harness"], "product_adaptive_code_agent")
        self.assertIs(no_memory["component_inputs"]["enable_memory"], False)

        adaptive = self.load("product_adaptive_code_agent")
        inputs = adaptive["component"]["inputs"]
        for name in ("enable_delegation", "enable_curation", "enable_compaction", "enable_tool_pruning"):
            self.assertIs(inputs[name]["default"], True)
        nodes = adaptive["pipeline"]["nodes"]
        self.assertIn("ctx.enable_delegation == true", nodes["delegation_due"]["condition"])
        self.assertIn("ctx.enable_curation == true", nodes["curation_due"]["condition"])
        self.assertEqual(nodes["activate_discovered"]["edges"][0]["to"], "curation_probe")
        self.assertEqual(nodes["curation_probe"]["action"], "snapshot")
        self.assertIn("ctx.curation_probe.pressure.message_tokens_estimated >= ctx.curation_minimum_tokens", nodes["curation_due"]["condition"])
        self.assertGreaterEqual(inputs["curation_minimum_tokens"]["default"], 8000)
        self.assertTrue(inputs["enable_memory"]["default"])
        self.assertEqual(nodes["recall"]["minimum_overlap"], 1)
        self.assertEqual(nodes["remember_policy"]["edges"][1]["to"], "checkpoint_after")
        self.assertIn("ctx.enable_compaction == true", nodes["compaction_policy"]["condition"])
        self.assertIn("ctx.enable_compaction == true", nodes["post_tool_compaction_policy"]["condition"])
        self.assertIs(nodes["infer"]["reject_identical_tool_call"], False)
        self.assertEqual(nodes["repeat_guard"]["component_inputs"]["thresholds"], [2, 3, 5])
        self.assertEqual(nodes["reset_repeat_guard"]["component_inputs"]["thresholds"], [2, 3, 5])
        self.assertEqual(nodes["repeat_guard"]["edges"][0]["to"], "tool_pruning_policy")
        self.assertIn("ctx.enable_tool_pruning == true", nodes["tool_pruning_policy"]["condition"])
        self.assertEqual(nodes["tool_pruning_policy"]["edges"][1]["to"], "post_tool_compaction_policy")

        pressure_on = self.load("product_adaptive_pressure_lab")["pipeline"]["nodes"]["run_pressure_profile"]["component_inputs"]
        pressure_off = self.load("product_adaptive_pressure_no_context")["pipeline"]["nodes"]["run_pressure_without_context"]["component_inputs"]
        for name in ("context_limit_tokens", "context_high_watermark", "context_target_ratio", "context_minimum_savings_tokens"):
            self.assertEqual(pressure_on[name], pressure_off[name])
        self.assertIs(pressure_on["enable_curation"], True)
        self.assertIs(pressure_on["enable_compaction"], True)
        self.assertIs(pressure_on["enable_tool_pruning"], True)
        self.assertIs(pressure_off["enable_curation"], False)
        self.assertIs(pressure_off["enable_compaction"], False)
        self.assertIs(pressure_off["enable_tool_pruning"], False)
        self.assertGreaterEqual(pressure_on["context_limit_tokens"], 16384)

        prune_on = self.load("product_adaptive_tool_pruning_on")["pipeline"]["nodes"]["run"]["component_inputs"]
        prune_off = self.load("product_adaptive_tool_pruning_off")["pipeline"]["nodes"]["run"]["component_inputs"]
        self.assertEqual({k: v for k, v in prune_on.items() if k != "enable_tool_pruning"},
                         {k: v for k, v in prune_off.items() if k != "enable_tool_pruning"})
        self.assertIs(prune_on["enable_tool_pruning"], True)
        self.assertIs(prune_off["enable_tool_pruning"], False)

        compact_only = self.load("product_adaptive_compaction_only")["pipeline"]["nodes"]["run"]["component_inputs"]
        context_combo = self.load("product_adaptive_context_combo")["pipeline"]["nodes"]["run"]["component_inputs"]
        factorial = {
            (False, False): prune_off,
            (True, False): prune_on,
            (False, True): compact_only,
            (True, True): context_combo,
        }
        ignored = {"enable_tool_pruning", "enable_compaction"}
        fixed = {key: value for key, value in prune_off.items() if key not in ignored}
        for (pruning, compaction), inputs in factorial.items():
            self.assertEqual({key: value for key, value in inputs.items() if key not in ignored}, fixed)
            self.assertIs(inputs["enable_tool_pruning"], pruning)
            self.assertIs(inputs["enable_compaction"], compaction)

        compactor = self.load("component_context_compactor")
        self.assertGreaterEqual(compactor["component"]["inputs"]["minimum_savings_tokens"]["default"], 1)
        self.assertEqual(
            compactor["pipeline"]["nodes"]["conversation_out"]["minimum_savings_tokens"],
            "$ctx.minimum_savings_tokens",
        )

    def test_capability_discovery_ranks_refined_tool_evidence_before_model_selection(self):
        nodes = self.load("component_capability_discovery")["pipeline"]["nodes"]
        self.assertEqual(nodes["search_tools"]["edges"][0]["to"], "activate_refined")
        self.assertEqual(nodes["activate_refined"]["action"], "activate_best_from_search_evidence")
        self.assertEqual(nodes["activate_refined"]["edges"][0], {"condition": "activated", "to": "mark"})
        self.assertEqual(nodes["activation_tools"]["edges"][0]["to"], "validate_selected")
        self.assertEqual(nodes["validate_selected"]["action"], "activate_best_from_search_evidence")
        self.assertGreaterEqual(nodes["fast_match"]["min_lexical_score"], 10.0)
        self.assertGreaterEqual(nodes["fast_match"]["min_semantic_score"], 0.62)

    def test_delegation_requires_child_local_cost_evidence(self):
        nodes = self.load("product_adaptive_code_agent")["pipeline"]["nodes"]
        condition = nodes["delegation_due"]["condition"]
        self.assertEqual(nodes["plan"]["edges"][0]["to"], "measure_delegation")
        self.assertEqual(nodes["measure_delegation"]["action"], "measure")
        self.assertEqual(nodes["measure_delegation"]["paths"], "$ctx.implementation_plan.delegation_candidate.child_paths")
        self.assertIn("ctx.delegation_scope.files >= 12", condition)
        self.assertIn("ctx.delegation_scope.bytes >= 12000", condition)
        self.assertEqual(nodes["delegation_due"]["edges"][1]["to"], "restore_full_parent_task")
        self.assertEqual(nodes["restore_full_parent_task"]["value"], "$ctx.request")
        self.assertEqual(nodes["restore_full_parent_paths"]["value"], [])
        self.assertEqual(nodes["restore_full_parent_paths"]["edges"][0]["to"], "checkpoint_before")
        fallback = nodes["plan"]["json_fallback"]["delegation_candidate"]
        self.assertEqual(fallback["estimated_child_tool_calls"], 0)
        self.assertEqual(fallback["estimated_child_context_chars"], 0)
        self.assertEqual(fallback["child_paths"], [])

    def test_each_turn_clears_stale_delegation_output_before_planning(self):
        nodes = self.load("product_adaptive_code_agent")["pipeline"]["nodes"]
        self.assertEqual(nodes["reset_feedback"]["edges"][0]["to"], "reset_delegation_result")
        self.assertEqual(nodes["reset_delegation_result"]["key"], "delegation_result")
        self.assertEqual(nodes["reset_delegation_result"]["value"], "")

    def test_verified_evolution_is_hot_loaded_on_the_primary_agent(self):
        config = self.load("product_adaptive_code_agent")
        nodes = config["pipeline"]["nodes"]
        outputs = nodes["evolve"]["component_outputs"]

        self.assertEqual(nodes["evolve"]["edges"][0]["to"], "evolved_ready")
        self.assertEqual(outputs["mutation"], "evolution_mutation_evidence")
        self.assertEqual(outputs["repair"], "evolution_repair_evidence")
        self.assertIn("verification_decision.verified == true", nodes["evolved_ready"]["condition"])
        self.assertEqual(nodes["activate_evolved_primary"]["agent"], "agent")
        self.assertEqual(nodes["activate_evolved_primary"]["action"], "activate_from_evidence")

    def test_skill_evolution_has_exclusive_verification_and_failure_quarantine(self):
        config = self.load("component_capability_evolver")
        nodes = config["pipeline"]["nodes"]

        self.assertTrue(nodes["conversation_in"]["include_usage"])
        self.assertEqual(nodes["mutation_gate"]["edges"][0]["to"], "verification_route")
        self.assertEqual(nodes["verify_skill"]["visible_tools"], ["verify_identity_skill"])
        self.assertEqual(nodes["verification_skill_repair"]["visible_tools"], ["verify_identity_skill"])
        self.assertEqual(nodes["verification_gate"]["edges"][1]["to"], "quarantine_mutation")
        self.assertEqual(nodes["verification_failed"]["edges"][0]["to"], "quarantine_mutation")
        self.assertEqual(nodes["quarantine_mutation"]["action"], "quarantine_from_evidence")

    def test_prompt_slots_render_next_to_literal_json_examples(self):
        prompt = _format_prompt(
            'Request: {request}\nAnswer: {answer}\nReturn {"complete":true}',
            {"request": "fix it", "answer": {"tests": "passed"}},
        )
        self.assertIn("Request: fix it", prompt)
        self.assertIn('Answer: {"tests": "passed"}', prompt)
        self.assertIn('Return {"complete":true}', prompt)

    def test_bounded_work_loops_always_reach_tail_nodes(self):
        expectations = {
            "product_adaptive_code_agent": "review_parallel",
            "product_core_code_agent": "checkpoint_after",
        }
        for name, tail in expectations.items():
            loop = self.load(name)["pipeline"]["nodes"]["work_loop"]
            routes = {(edge["condition"], edge["to"]) for edge in loop["edges"]}
            self.assertIn(("loop_break", tail), routes)
            self.assertIn(("loop_done", tail), routes)

    def test_large_delegation_fixture_has_two_disjoint_substantial_scopes(self):
        task = json.loads(
            (ROOT / "task_bench" / "tasks" / "product_large_dual_subsystem_repair.json").read_text(encoding="utf-8")
        )
        files = task["workspace"]["files"]
        slug_files = [path for path in files if path.startswith("slug_codec/")]
        quota_files = [path for path in files if path.startswith("quota_engine/")]
        self.assertGreaterEqual(len(slug_files), 14)
        self.assertGreaterEqual(len(quota_files), 14)
        self.assertFalse(set(slug_files) & set(quota_files))
        self.assertIn("product_adaptive_no_delegation", task["selection"]["compatible_harnesses"])
        self.assertIn("code_agent_team", task["selection"]["compatible_harnesses"])

    def test_context_endurance_profiles_are_matched_except_for_governance_switch(self):
        on = self.load("product_context_endurance_governed")["pipeline"]["nodes"]["run"]["component_inputs"]
        curation_only = self.load("product_context_endurance_curation_only")["pipeline"]["nodes"]["run"]["component_inputs"]
        off = self.load("product_context_endurance_ungoverned")["pipeline"]["nodes"]["run"]["component_inputs"]
        self.assertIs(on["enable_context_governance"], True)
        self.assertIs(off["enable_context_governance"], False)
        switches = {"enable_context_governance", "enable_curation", "enable_compaction"}
        self.assertEqual({k: v for k, v in on.items() if k not in switches}, {k: v for k, v in off.items() if k not in switches})
        component = self.load("product_context_endurance_agent")
        self.assertEqual(component["slots"]["governor"]["identity"], "context_governor_lite")
        compact_only = self.load("product_context_endurance_compaction_only")["pipeline"]["nodes"]["run"]["component_inputs"]
        self.assertIs(compact_only["enable_curation"], False)
        self.assertIs(compact_only["enable_compaction"], True)
        self.assertIs(curation_only["enable_curation"], True)
        self.assertIs(curation_only["enable_compaction"], False)
        ignored = {"enable_context_governance", "enable_curation", "enable_compaction"}
        fixed = {key: value for key, value in off.items() if key not in ignored}
        for inputs in (on, curation_only, compact_only, off):
            self.assertEqual({key: value for key, value in inputs.items() if key not in ignored}, fixed)
        task = json.loads((ROOT / "task_bench" / "tasks" / "product_context_endurance_ledger.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(task["steps"]), 25)
        self.assertIn("7319|zircon|src/engine.py|AMBER", task["steps"][-1]["evaluation"]["checks"][0]["value"])

    def test_cross_session_memory_fixture_starts_a_fresh_trajectory(self):
        task = json.loads((ROOT / "task_bench" / "tasks" / "product_cross_session_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(len(task["steps"]), 2)
        self.assertFalse(task["steps"][1]["resume_trajectory"])
        self.assertIn("product_adaptive_no_memory", task["selection"]["compatible_harnesses"])

    def test_large_observation_fixture_keeps_contract_and_bug_at_opposite_ends(self):
        task = json.loads((ROOT / "task_bench" / "tasks" / "product_large_observation_repair.json").read_text(encoding="utf-8"))
        source = task["workspace"]["files"]["generated_rules.py"]
        self.assertGreater(len(source), 40_000)
        self.assertLess(source.index("CONTRACT:"), 1_000)
        self.assertGreater(source.index("def artifact_digest"), 40_000)
        self.assertEqual(
            task["selection"]["compatible_harnesses"],
            [
                "product_adaptive_tool_pruning_off",
                "product_adaptive_tool_pruning_on",
                "product_adaptive_compaction_only",
                "product_adaptive_context_combo",
            ],
        )


if __name__ == "__main__":
    unittest.main()
