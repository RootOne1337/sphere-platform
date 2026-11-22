import unittest

from scripts.pilot.audit_saved_match_coverage import unique_query_band_counts


class MatchCoverageTests(unittest.TestCase):
    def test_deduplicates_same_query_across_candidates(self):
        result = unique_query_band_counts(
            [1, 1, 2, 3], [[10, 100], [10, 100], [20, 200], [30, 400]]
        )
        self.assertEqual(result, [1, 1, 1])

    def test_rejects_conflicting_positions_and_out_of_bounds(self):
        with self.assertRaisesRegex(ValueError, "query_position_mismatch"):
            unique_query_band_counts([1, 1], [[10, 10], [11, 10]])
        with self.assertRaisesRegex(ValueError, "match_coverage_invalid"):
            unique_query_band_counts([1], [[960, 20]])


if __name__ == "__main__":
    unittest.main()
