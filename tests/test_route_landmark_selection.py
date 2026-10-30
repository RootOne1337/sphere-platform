import unittest

import numpy as np

from scripts.pilot.route_landmark_builder import select_spatially_diverse


class LandmarkSelectionTests(unittest.TestCase):
    def setUp(self):
        self.matrices = [np.hstack((np.eye(3), np.zeros((3, 1)))) for _ in range(8)]
        self.K = np.eye(3)

    @staticmethod
    def point(x, y, view):
        return (3, (x, y, 1.), np.zeros(128), (view,))

    def test_budget_reserves_varied_time_and_image_regions(self):
        road = [self.point(100+i, 450, 0) for i in range(100)]
        facade = [self.point(700, 180, 7)]
        selected, report = select_spatially_diverse(road+facade, self.matrices, self.K, 4)
        self.assertEqual(len(selected), 4)
        self.assertIn(facade[0], selected)
        self.assertEqual(report['selected_count'], 4)
        self.assertEqual(report['grid_buckets'], 2)

    def test_unconstrained_map_keeps_original_order(self):
        rows = [self.point(400, 200, 7), self.point(100, 400, 0)]
        selected, report = select_spatially_diverse(rows, self.matrices, self.K, 3)
        self.assertIs(selected[0], rows[0])
        self.assertEqual(report['candidate_count'], 2)

    def test_unknown_projection_does_not_claim_a_bucket(self):
        rows = [self.point(400, 200, 0), (3, (0., 0., -1.), np.zeros(128), (0,))]
        selected, report = select_spatially_diverse(rows, self.matrices, self.K, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(report['unprojectable_count'], 1)
        self.assertEqual(report['grid_buckets'], 1)

    def test_checkpoint_is_called_for_bounded_selection(self):
        observed = []
        select_spatially_diverse([self.point(100, 100, 0)] * 513, self.matrices, self.K, 10,
                                 checkpoint=lambda: observed.append(1))
        self.assertEqual(len(observed), 3)
