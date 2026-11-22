import unittest

import numpy as np

from scripts.pilot.compare_independent_capture_places import sample_frames


class IndependentSamplingTests(unittest.TestCase):
    def test_regular_recording_selects_increasing_distinct_source_frames(self):
        times = np.arange(0, 12, 0.04)
        selected = sample_frames(times)
        self.assertEqual(len(selected), 50)
        self.assertEqual(len(set(selected)), len(selected))
        self.assertTrue(all(a < b for a, b in zip(selected, selected[1:])))
        self.assertAlmostEqual(times[selected[0]], 0.2)

    def test_bad_or_too_short_timebases_are_rejected(self):
        for times in ([0, 1, 1, 2], [0, float("nan"), 2], [0, 0.2, 0.4]):
            with self.assertRaisesRegex(ValueError, "query_sampling_invalid"):
                sample_frames(times)

    def test_sparse_frames_are_not_duplicated_as_evidence(self):
        times = np.arange(0, 12, 0.5)
        selected = sample_frames(times)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertLess(len(selected), 50)
