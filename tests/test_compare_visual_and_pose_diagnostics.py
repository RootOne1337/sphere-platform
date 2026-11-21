import unittest

from scripts.pilot.compare_visual_and_pose_diagnostics import compare


class VisualPoseCrossCheckTests(unittest.TestCase):
    def setUp(self):
        self.place = {
            "same_capture": True,
            "physical_actions": 0,
            "samples": [
                {"source_index": 4, "seconds": 10.0, "state": "matched", "reference_seconds": 10.2},
                {"source_index": 5, "seconds": 10.2, "state": "unknown", "reference_seconds": None},
            ],
        }
        self.pose = {
            "independent_pass": False,
            "physical_actions": 0,
            "samples": [
                {
                    "source_index": 4,
                    "seconds": 10.0,
                    "lightglue_pnp": True,
                    "lightglue_ambiguous": False,
                    "center_pair_discontinuity": True,
                },
                {
                    "source_index": 5,
                    "seconds": 10.2,
                    "lightglue_pnp": False,
                    "lightglue_ambiguous": False,
                    "center_pair_discontinuity": None,
                },
                {
                    "source_index": 6,
                    "seconds": 10.4,
                    "lightglue_pnp": True,
                    "lightglue_ambiguous": False,
                    "center_pair_discontinuity": False,
                },
            ],
        }

    def test_exact_identity_join_and_non_authorization(self):
        result = compare(self.place, self.pose)
        self.assertEqual(
            (result["pose_frames"], result["shared_frames"], result["shared_jumps"]), (3, 2, 1)
        )
        self.assertEqual(result["jumps_visual_reference_within_1s"], 1)
        self.assertFalse(result["execution_qualified"])

    def test_rejects_wrong_time_duplicate_ids_and_nonoffline(self):
        self.place["samples"][0]["seconds"] = 11.0
        with self.assertRaisesRegex(ValueError, "cross_probe_time_mismatch"):
            compare(self.place, self.pose)
        self.place["samples"][0]["seconds"] = 10.0
        self.place["samples"].append(self.place["samples"][0])
        with self.assertRaisesRegex(ValueError, "cross_probe_duplicate_frames"):
            compare(self.place, self.pose)
        self.place["samples"].pop()
        self.pose["physical_actions"] = 1
        with self.assertRaisesRegex(ValueError, "cross_probe_scope_mismatch"):
            compare(self.place, self.pose)


if __name__ == "__main__":
    unittest.main()
