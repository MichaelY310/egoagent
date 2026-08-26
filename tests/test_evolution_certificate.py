from __future__ import annotations

import unittest

from self_evolution.evolution_certificate import issue_evolution_certificate


EVIDENCE = [
    {"source": "task_run", "lineage_id": "run-a", "observation": "failure reproduced"},
    {"source": "verified_test", "lineage_id": "checker-b", "observation": "independent deterministic reproduction"},
]


def measurements(*, skill_gain=.12, harness_gain=.08, interaction=.05, protected=-.005):
    rows = []
    values = {(): .50, ("skill",): .50 + skill_gain, ("harness",): .50 + harness_gain, ("harness", "skill"): .50 + skill_gain + harness_gain + interaction}
    for split in ("validation", "heldout"):
        for task in range(12):
            wobble = .01 if task % 2 else 0
            for active, value in values.items():
                rows.append({"split": split, "task_id": f"{split}-{task}", "active_artifacts": list(active), "success": min(1, value + wobble), "within_budget": True})
    for task in range(12):
        rows.append({"split": "protected", "task_id": f"protected-{task}", "active_artifacts": [], "success": .90})
        rows.append({"split": "protected", "task_id": f"protected-{task}", "active_artifacts": ["harness", "skill"], "success": .90 + protected})
        rows.append({"split": "protected", "task_id": f"protected-{task}", "active_artifacts": ["skill"], "success": .90})
        rows.append({"split": "protected", "task_id": f"protected-{task}", "active_artifacts": ["harness"], "success": .90})
    return rows


def issue(rows, **overrides):
    args = dict(
        update_id="update-1",
        artifacts=[{"id": "skill", "kind": "skill"}, {"id": "harness", "kind": "harness"}],
        measurements=rows,
        evidence=EVIDENCE,
        activation={"skill": 24, "harness": 24},
        portability=[{"target": f"fresh-{index}", "baseline": {"success": .4}, "candidate": {"success": .5}} for index in range(8)],
        verifier_mutants=[{"id": f"m{index}", "relevant": True, "killed": index < 9} for index in range(10)],
        minimum_total_gain=.03,
    )
    args.update(overrides)
    return issue_evolution_certificate(**args)


class EvolutionCertificateTests(unittest.TestCase):
    def test_accepts_activated_necessary_portable_noninterfering_update(self):
        certificate = issue(measurements())
        self.assertEqual(certificate["decision"], "accept")
        self.assertEqual(certificate["verifier_mutation_score"]["score"], .9)
        self.assertTrue(certificate["causal_effects"]["interactions"])
        self.assertEqual(len(certificate["certificate_sha256"]), 64)

    def test_rejects_bundled_artifact_that_is_not_necessary(self):
        certificate = issue(measurements(harness_gain=0, interaction=0))
        self.assertEqual(certificate["decision"], "reject")
        self.assertTrue(any("non-necessary artifacts" in reason for reason in certificate["reasons"]))

    def test_rejects_protected_regression_even_with_task_gain(self):
        certificate = issue(measurements(protected=-.2))
        self.assertEqual(certificate["decision"], "reject")
        self.assertTrue(any("non-interference" in reason for reason in certificate["reasons"]))

    def test_rejects_validation_only_overfit(self):
        rows = measurements()
        baseline = {
            row["task_id"]: row["success"]
            for row in rows
            if row["split"] == "heldout" and not row["active_artifacts"]
        }
        for row in rows:
            if row["split"] == "heldout" and row["active_artifacts"]:
                row["success"] = baseline[row["task_id"]]
        certificate = issue(rows)
        self.assertEqual(certificate["decision"], "reject")
        self.assertTrue(any("sealed heldout" in reason for reason in certificate["reasons"]))

    def test_abstains_without_portability_or_semantic_mutation_evidence(self):
        certificate = issue(measurements(), portability=[], verifier_mutants=[])
        self.assertEqual(certificate["decision"], "abstain")
        self.assertEqual(len(certificate["reasons"]), 2)


if __name__ == "__main__":
    unittest.main()
