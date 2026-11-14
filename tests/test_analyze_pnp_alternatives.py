import unittest

from scripts.pilot.analyze_pnp_alternatives import analyze


class PnpAlternativeTests(unittest.TestCase):
    def test_strong_motion_consistent_candidate_is_reported_not_selected(self):
        def candidate(view, x, inliers):
            return {"view": view, "center": [x, 0, 0], "inliers": inliers, "pnp_passed": True}

        report = {
            "samples": [
                {"source_index": 1, "seconds": 0.0, "candidates": [candidate(0, 2.5, 100)]},
                {
                    "source_index": 2,
                    "seconds": 0.2,
                    "candidates": [candidate(1, 4, 100), candidate(2, 3, 80)],
                },
            ]
        }
        states = {
            "samples": [
                {"source_index": 1, "seconds": 0.0, "lightglue_unambiguous_candidate": True},
                {"source_index": 2, "seconds": 0.2, "lightglue_unambiguous_candidate": True},
            ]
        }
        geometry = {"cameras": [{"center": [0, 0, 0]}, {"center": [1, 0, 0]}]}
        result = analyze(report, states, geometry)
        self.assertEqual((result["jump_count"], result["jumps_with_strong_alternative"]), (1, 1))
        self.assertEqual(result["jumps"][0]["candidate_views"], [2])
        self.assertFalse(result["execution_qualified"])

    def test_frame_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "alternatives_sample_mismatch"):
            analyze(
                {"samples": [{"source_index": 1, "seconds": 0}]},
                {"samples": [{"source_index": 2, "seconds": 0}]},
                {"cameras": []},
            )


if __name__ == "__main__":
    unittest.main()
