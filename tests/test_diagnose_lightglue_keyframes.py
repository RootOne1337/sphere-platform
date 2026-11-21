import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from scripts.pilot.diagnose_lightglue_keyframes import checkpoint, validate_match_pairs


class MatchPairValidationTests(unittest.TestCase):
    def test_unique_integer_matches_and_empty_are_valid(self):
        valid = np.array([[0, 2], [1, 0]], dtype=np.int64)
        self.assertIs(validate_match_pairs(valid, 2, 3), valid)
        self.assertEqual(len(validate_match_pairs(np.empty((0, 2), np.int64), 0, 0)), 0)

    def test_repeated_negative_out_of_range_and_float_are_rejected(self):
        for pairs in (
            np.array([[0, 0], [0, 1]]),
            np.array([[0, 0], [1, 0]]),
            np.array([[-1, 0]]),
            np.array([[0, 3]]),
            np.array([[0.0, 1.0]]),
        ):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                validate_match_pairs(pairs, 2, 3)

    def test_checkpoint_keeps_twelve_gib_floor_and_records_refusal(self):
        with (
            TemporaryDirectory() as folder,
            patch("scripts.pilot.diagnose_lightglue_keyframes.collect", return_value={}),
            patch(
                "scripts.pilot.diagnose_lightglue_keyframes.evaluate",
                return_value=["ram_headroom_low"],
            ) as evaluate,
        ):
            with self.assertRaisesRegex(RuntimeError, "lightglue_resource_guard"):
                checkpoint(Path(folder))
            self.assertEqual(evaluate.call_args.kwargs["min_ram_gib"], 12)
            self.assertTrue((Path(folder) / "resource-refusal.json").is_file())


if __name__ == "__main__":
    unittest.main()
