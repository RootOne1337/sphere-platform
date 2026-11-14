import unittest

from scripts.pilot.analyze_pnp_candidate_budget import analyze


class CandidateBudgetTests(unittest.TestCase):
    def test_limited_budget_exposes_hidden_conflict(self):
        def c(x, count):
            return {
                "pnp_passed": True,
                "inliers": count,
                "center": [x, 0, 0],
                "matching_ms": 2,
                "verify_ms": 1,
            }

        report = {
            "independent_pass": False,
            "physical_actions": 0,
            "samples": [{"feature_ms": 3, "candidates": [c(0, 100), c(4, 90)]}],
        }
        geometry = {"cameras": [{"center": [0, 0, 0]}, {"center": [1, 0, 0]}]}
        r = analyze(report, geometry)
        self.assertEqual(r["budgets"][0]["conflicts_hidden_vs_recorded_set"], 1)
        self.assertEqual(r["budgets"][1]["conflicts"], 1)
        self.assertEqual(r["budgets"][0]["compute_ms_p50"], 6)
        self.assertFalse(r["execution_qualified"])

    def test_rejects_nonoffline_evidence(self):
        with self.assertRaisesRegex(ValueError, "candidate_budget_scope_invalid"):
            analyze(
                {"independent_pass": False, "physical_actions": 1, "samples": [{}]}, {"cameras": []}
            )


if __name__ == "__main__":
    unittest.main()
