from __future__ import annotations

import unittest

from experiments.real_layer_evolution.issue_evocert import build_payload


class RealPilotCertificateAdapterTests(unittest.TestCase):
    def test_refuses_to_fabricate_missing_research_evidence(self):
        report = {
            "families": [{
                "family": "logq",
                "selection": {"kind": "knowledge"},
                "rows": [{
                    "split": "validation", "task_id": "v", "repetition": 1,
                    "static": {"success": True}, "knowledge": {"success": True, "status": "completed"},
                }, {
                    "split": "heldout", "task_id": "h", "repetition": 1,
                    "static": {"success": True}, "knowledge": {"success": True, "status": "completed"},
                }],
            }],
        }
        result = build_payload(report, "logq")
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["real_measurements"]), 4)
        self.assertIn("paired protected-task executions", result["missing_evidence"])


if __name__ == "__main__":
    unittest.main()
