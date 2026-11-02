import unittest

from scripts.pilot.audit_graph_track_retention import band_counts


class GraphTrackRetentionTests(unittest.TestCase):
    def test_counts_verified_and_shared_track_separately(self):
        total, shared = band_counts([10, 20, 40, 80, 90], [1, -1, 3, 4, 5], [1, 2, 7, 4, -1], 90)
        self.assertEqual(total, [2, 1, 1])
        self.assertEqual(shared, [1, 0, 1])

    def test_rejects_inconsistent_input(self):
        with self.assertRaisesRegex(ValueError, "track_retention_input_invalid"):
            band_counts([1, 2], [1], [1], 90)
        with self.assertRaisesRegex(ValueError, "track_retention_input_invalid"):
            band_counts([float("nan")], [1], [1], 90)


if __name__ == "__main__":
    unittest.main()
