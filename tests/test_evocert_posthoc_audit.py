import unittest

from experiments.evocert_real_pilot.posthoc_audit import audit_report


class EvoCertPosthocAuditTests(unittest.TestCase):
    def test_distinguishes_advertisement_from_invocation_and_flags_floor(self):
        def cell(success=0, *, k=False, tools=(), status="passed", error=None):
            return {
                "success": success,
                "activation": {"K": k},
                "tools": [{"name": name} for name in tools],
                "status": status,
                "runtime_error": error,
            }

        report = {
            "stamp": "fixture",
            "families": [{
                "family": "logq",
                "rows": [
                    {
                        "split": "heldout", "task_id": "held",
                        "none": cell(), "K": cell(k=True),
                        "IK": cell(k=True, tools=("logq_operation_protocol",)),
                        "KF": cell(k=True), "IKF": cell(k=True),
                    },
                    {
                        "split": "protected", "task_id": "protected",
                        **{
                            variant: cell(k="K" in variant)
                            for variant in ("none", "I", "K", "F", "IK", "IF", "KF", "IKF")
                        },
                    },
                ],
            }],
        }
        result = audit_report(report)
        family = result["families"][0]
        self.assertEqual(family["knowledge_activation"]["advertised_rate"], 1.0)
        self.assertEqual(family["knowledge_activation"]["invoked_rate"], 0.125)
        self.assertTrue(family["protected_gate"]["all_incumbents_at_floor"])
        self.assertFalse(family["protected_gate"]["non_regression_claim_informative"])


if __name__ == "__main__":
    unittest.main()
