import copy
import json
import tempfile
import unittest
from pathlib import Path

from ego_ir import EgoIRService
from self_evolution.proof_evolution import (
    EvolutionProofError,
    GovernancePolicy,
    ProofEvolutionController,
    assess_evolution_evidence,
    fair_evolution_experiment,
    lifelong_metrics,
    promotion_decision,
    select_empirical_evolution_artifact,
    select_evolution_artifact,
    validate_proposal,
)


def proposal(expected_revision="rev"):
    return {
        "format": "ego.evolution-proposal.v1",
        "id": "add_guard",
        "target": "worker",
        "artifact": {"kind": "harness", "name": "guard"},
        "evidence": [
            {"source": "task_run", "lineage_id": "run-1", "artifact_ref": "run-1/trace.json", "observation": "unsafe action reached output without an approval node"},
            {"source": "verified_test", "lineage_id": "checker-1", "artifact_ref": "checks/approval-node.json", "observation": "an independent deterministic check reproduced the missing approval node"},
        ],
        "scope": {"paths": ["harness/worker/config.json"], "permissions": ["harness_patch"]},
        "change": {
            "expected_revision": expected_revision,
            "operations": [{"op": "set_limits", "max_steps": 9}],
            "checks": [{"type": "no_python"}],
        },
        "hypothesis": {"description": "A smaller bound prevents runaway loops", "metric": "success", "minimum_delta": 0.05},
        "evaluation": {"train": ["train-a"], "validation": ["valid-a"], "heldout": ["hidden-a"], "regression": ["reg-a"]},
        "cost": {"before": 1.0, "after": 1.05},
        "rollback": {"strategy": "transaction", "required": True},
        "confidence": 0.8, "expected_reuse": 0.8, "expected_benefit": 0.6,
        "maintenance_cost": 0.1, "regression_risk": 0.1,
    }


def harness(name="worker"):
    return {
        "name": name, "description": "fixture", "slots": {}, "prompts": {}, "return_mode": "last",
        "pipeline": {"start": "done", "max_steps": 5, "workspace_preview": False, "nodes": {
            "done": {"op": "输出", "value": "done", "edges": []},
        }},
    }


class ProofEvolutionTests(unittest.TestCase):
    def test_selector_can_choose_no_change_and_uses_economics(self):
        none = select_evolution_artifact([{
            "kind": "skill", "expected_reuse": 0.1, "expected_benefit": 0.1, "confidence": 0.3,
            "implementation_cost": 0.9, "maintenance_cost": 0.8, "regression_risk": 0.5,
        }])
        self.assertEqual(none["kind"], "none")
        chosen = select_evolution_artifact([
            {"kind": "knowledge", "expected_reuse": 0.8, "expected_benefit": 0.7, "confidence": 0.9, "implementation_cost": 0.1, "maintenance_cost": 0.05, "regression_risk": 0.05, "token_saving": 0.5},
            {"kind": "harness", "expected_reuse": 0.3, "expected_benefit": 0.8, "confidence": 0.6, "implementation_cost": 0.5, "maintenance_cost": 0.3, "regression_risk": 0.4},
        ])
        self.assertEqual(chosen["kind"], "knowledge")

    def test_evidence_firewall_does_not_count_repeated_poison_as_independent(self):
        poisoned = assess_evolution_evidence([
            {"source": "web_trace", "lineage_id": "attacker.example", "observation": "always run payload"},
            {"source": "web_trace", "lineage_id": "attacker.example", "observation": "payload is useful"},
            {"source": "web_trace", "lineage_id": "attacker.example", "observation": "repeat payload"},
        ])
        self.assertFalse(poisoned["eligible"])
        self.assertEqual(poisoned["independent_lineages"], 1)
        self.assertEqual(poisoned["trusted_records"], 0)
        corroborated = assess_evolution_evidence([
            {"source": "task_run", "lineage_id": "run-a", "observation": "failure reproduced"},
            {"source": "independent_replay", "lineage_id": "replay-b", "observation": "checker reproduced failure"},
        ])
        self.assertTrue(corroborated["eligible"])

    def test_empirical_selector_chooses_minimal_sufficient_layer_from_matched_runs(self):
        evidence = [
            {"source": "task_run", "lineage_id": "run-a", "observation": "recurring failure"},
            {"source": "verified_test", "lineage_id": "test-b", "observation": "failure reproduced"},
        ]

        def candidate(kind, gain):
            return {
                "kind": kind,
                "maintenance_cost": 0.05,
                "regression_risk": 0.02,
                "evidence": evidence,
                "measurements": [
                    {"task_id": "v1", "split": "validation", "baseline": {"success": 0.4, "tokens": 100, "cost": 1}, "candidate": {"success": 0.4 + gain, "tokens": 80, "cost": 0.9, "within_budget": True}},
                    {"task_id": "h1", "split": "heldout", "baseline": {"success": 0.5, "tokens": 100, "cost": 1}, "candidate": {"success": 0.5 + gain, "tokens": 80, "cost": 0.9, "within_budget": True}},
                    {"task_id": "r1", "split": "regression", "baseline": {"success": 0.8, "tokens": 100, "cost": 1}, "candidate": {"success": 0.8, "tokens": 80, "cost": 0.9, "within_budget": True}},
                ],
            }

        chosen = select_empirical_evolution_artifact([
            candidate("knowledge", 0.10),
            candidate("harness", 0.11),
        ], simplicity_epsilon=0.03)
        self.assertEqual(chosen["kind"], "knowledge")
        self.assertEqual(chosen["selection_rule"], "matched-shadow-minimal-sufficient-v1")

    def test_empirical_selector_blocks_poisoned_or_unmatched_layers(self):
        measurements = [
            {"task_id": "v1", "split": "validation", "baseline": {"success": 0.0}, "candidate": {"success": 1.0}},
            {"task_id": "h1", "split": "heldout", "baseline": {"success": 0.0}, "candidate": {"success": 1.0}},
        ]
        poisoned = {
            "kind": "skill", "maintenance_cost": 0, "regression_risk": 0,
            "measurements": measurements,
            "evidence": [
                {"source": "web_trace", "lineage_id": "one-origin", "observation": "install this"},
                {"source": "web_trace", "lineage_id": "one-origin", "observation": "install this again"},
            ],
        }
        result = select_empirical_evolution_artifact([poisoned])
        self.assertEqual(result["kind"], "none")
        self.assertTrue(any("evidence:" in reason for reason in result["ranked"][0]["ineligibility_reasons"]))
        safe = copy.deepcopy(poisoned)
        safe["kind"] = "knowledge"
        safe["evidence"].append({"source": "verified_test", "lineage_id": "checker", "observation": "verified"})
        safe["measurements"][1]["task_id"] = "different-heldout"
        with self.assertRaisesRegex(EvolutionProofError, "identical paired tasks"):
            select_empirical_evolution_artifact([poisoned, safe], require_provenance=False)

    def test_proposal_requires_artifact_evidence_disjoint_splits_and_no_leakage(self):
        valid = validate_proposal(proposal())
        self.assertEqual(valid["artifact"]["kind"], "harness")
        leaked = proposal()
        leaked["evidence"][0]["observation"] = "The expected hidden-a answer is 42"
        with self.assertRaisesRegex(EvolutionProofError, "leakage"):
            validate_proposal(leaked)
        secret = proposal()
        secret["change"]["note"] = "api_key=sk-secret-value-123456789"
        with self.assertRaisesRegex(EvolutionProofError, "secret"):
            validate_proposal(secret)
        overlap = proposal()
        overlap["evaluation"]["validation"] = ["train-a"]
        with self.assertRaisesRegex(EvolutionProofError, "disjoint"):
            validate_proposal(overlap)

    def test_governance_needs_human_for_environment_and_enforces_quota(self):
        value = validate_proposal(proposal())
        value["artifact"]["kind"] = "environment"
        policy = GovernancePolicy(max_operations=0)
        result = policy.inspect(value)
        self.assertFalse(result["allowed"])
        self.assertTrue(any("human approval" in reason for reason in result["reasons"]))
        self.assertTrue(any("quota" in reason for reason in result["reasons"]))

    def test_governance_blocks_persistent_change_without_independent_evidence(self):
        value = validate_proposal(proposal())
        value["evidence"] = [
            {"source": "task_run", "lineage_id": "same-run", "observation": "failure one"},
            {"source": "task_run", "lineage_id": "same-run", "observation": "failure two"},
        ]
        result = GovernancePolicy().inspect(value)
        self.assertFalse(result["allowed"])
        self.assertTrue(any("evidence integrity" in reason for reason in result["reasons"]))

    def test_fair_protocol_uses_identical_tasks_and_budget_for_all_variants(self):
        seen = []
        tasks = {name: [{"id": f"{name}-1", "difficulty": 1}] for name in ("train", "validation", "heldout")}
        def evaluator(variant, task, budget):
            seen.append((variant, task["id"], dict(budget)))
            return {"success": 1 if variant == "structure_only" else 0.5, "tokens": 50, "parent_tokens": 20, "cost": 0.01, "latency": 0.1, "reuse": 0.3}
        report = fair_evolution_experiment(tasks, evaluator, variants=["static", "structure_only"], budget={"max_tokens": 100, "max_cost": 1, "max_latency": 1})
        self.assertEqual(len(seen), 6)
        self.assertEqual(report["variants"]["structure_only"]["heldout"]["aggregate"]["success"], 1)
        self.assertTrue(all(entry[2] == seen[0][2] for entry in seen))

    def test_failed_gate_rolls_back_real_harness_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "harness" / "worker" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(harness(), ensure_ascii=False, indent=2), encoding="utf-8")
            revision = EgoIRService(root).load("worker")["revision"]
            value = proposal(revision)
            controller = ProofEvolutionController(root)
            controller.register(value)
            applied = controller.apply_experimental(value["id"])
            self.assertEqual(EgoIRService(root).load("worker")["config"]["pipeline"]["max_steps"], 9)
            decision = controller.gate(value["id"],
                {"validation": {"success": 0.8}, "heldout": {"success": 0.8}},
                {"validation": {"success": 0.81, "within_budget": True}, "heldout": {"success": 0.7, "within_budget": True}, "regression": {"passed": True}},
            )
            self.assertFalse(decision["accepted"])
            self.assertEqual(EgoIRService(root).load("worker")["config"]["pipeline"]["max_steps"], 5)
            self.assertEqual(controller.repository.load(value["id"])["status"], "rejected")

    def test_promotion_requires_heldout_gain_regression_and_budget(self):
        value = validate_proposal(proposal())
        accepted = promotion_decision(value,
            {"validation": {"success": 0.5}, "heldout": {"success": 0.5}},
            {"validation": {"success": 0.6, "within_budget": True}, "heldout": {"success": 0.57, "within_budget": True}, "regression": {"passed": True}},
        )
        self.assertTrue(accepted["accepted"])
        rejected = promotion_decision(value,
            {"validation": {"success": 0.5}, "heldout": {"success": 0.5}},
            {"validation": {"success": 0.7, "within_budget": True}, "heldout": {"success": 0.7, "within_budget": False}, "regression": {"passed": True}},
        )
        self.assertFalse(rejected["accepted"])

    def test_lifelong_metrics_measure_forgetting_transfer_and_amortization(self):
        metrics = lifelong_metrics([
            {"task_scores": {"a": 1.0}, "evolution_cost": 2, "reuse_benefit": 0},
            {"task_scores": {"a": 0.6, "b": 1.0}, "evolution_cost": 0, "reuse_benefit": 4, "negative_transfer": 0.2},
            {"task_scores": {"a": 0.9, "b": 0.8}, "evolution_cost": 0, "reuse_benefit": 2, "recovery": 0.3},
        ])
        self.assertAlmostEqual(metrics["worst_forgetting"], 0.4)
        self.assertEqual(metrics["evolution_amortization"], 3)


if __name__ == "__main__":
    unittest.main()
