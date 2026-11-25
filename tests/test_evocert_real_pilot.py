import unittest

from experiments.evocert_real_pilot.analyze import analyze_family, canonical_variant


class EvoCertRealPilotAnalysisTests(unittest.TestCase):
    def test_variant_order_is_canonical(self):
        self.assertEqual(canonical_variant(["F", "I"]), "IF")
        self.assertEqual(canonical_variant([]), "none")

    def test_factorial_oracle_prefers_minimal_coalition(self):
        rows = []
        for split in ("validation", "heldout", "protected"):
            row = {"split": split}
            for variant in ("none", "I", "K", "F", "IK", "IF", "KF", "IKF"):
                success = 1.0 if (split != "protected" and "I" in variant) else 0.0
                if split == "protected":
                    success = 1.0
                row[variant] = {
                    "success": success,
                    "tokens": 100 + len(variant),
                    "status": "completed",
                    "activation": {"K": "K" in variant},
                }
            rows.append(row)
        result = analyze_family({"family": "fixture", "rows": rows})
        self.assertEqual(result["decisions"]["factorial_oracle"], "I")
        self.assertTrue(result["decisions"]["unnecessary_IKF_admission"]["seal_style"])

    def test_detects_pure_three_way_interaction(self):
        rows = []
        for split in ("validation", "heldout", "protected"):
            row = {"split": split}
            for variant in ("none", "I", "K", "F", "IK", "IF", "KF", "IKF"):
                success = 1.0 if split != "protected" and variant == "IKF" else 0.0
                if split == "protected":
                    success = 1.0
                row[variant] = {
                    "success": success,
                    "tokens": 100,
                    "status": "completed",
                    "activation": {"K": "K" in variant},
                }
            rows.append(row)
        result = analyze_family({"family": "fixture", "rows": rows})
        self.assertEqual(result["interactions"]["IKF"], 1.0)
        self.assertEqual(result["decisions"]["factorial_oracle"], "IKF")


if __name__ == "__main__":
    unittest.main()
