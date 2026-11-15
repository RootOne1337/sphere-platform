
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest

import cv2 as cv
import numpy as np

from motor_worker.route_localization import RouteLocalizer
from motor_worker.route_xfeat_fast import _FastMeasuredSolve


class FastXFeatTests(unittest.TestCase):
    def test_short_ap3p_preserves_consensus_and_rejects_incompatible_points(self):
        rng = np.random.default_rng(401)
        world = rng.uniform((-3., -2., 5.), (3., 2., 10.), (80, 3))
        intrinsics = np.array([[650., 0., 480.], [0., 650., 270.], [0., 0., 1.]])
        pixels = cv.projectPoints(world, np.zeros(3), np.zeros(3), intrinsics, None)[0].reshape(-1, 2)
        pixels += rng.normal(0, .35, pixels.shape)
        pixels[:30] = rng.uniform((0., 0.), (960., 540.), (30, 2))
        context = SimpleNamespace(cv=cv, np=np, K=intrinsics, _ransac_trials=120)
        full = RouteLocalizer._verify_correspondences(context, world, pixels)
        fast = _FastMeasuredSolve._verify_correspondences(context, world, pixels)
        self.assertIsNotNone(full)
        self.assertIsNotNone(fast)
        self.assertEqual(full[2], fast[2])
        np.testing.assert_allclose(fast[0], full[0], atol=.01)
        random_image = rng.uniform((0., 0.), (960., 540.), (80, 2))
        self.assertIsNone(_FastMeasuredSolve._verify_correspondences(context, world, random_image))
        planar = world.copy()
        planar[:, 2] = 6.
        self.assertIsNone(_FastMeasuredSolve._verify_correspondences(context, planar, pixels))

    def test_joins_the_whole_ranked_batch_before_stopping_at_deadline(self):
        now = [1.]
        measured = []

        def verify(index, reference, pixels, descriptors):
            measured.append(index)
            now[0] = 1.27
            return index

        with ThreadPoolExecutor(max_workers=2) as pool:
            context = SimpleNamespace(clock=lambda: now[0], last_received=1.,
                _verification_pool=pool, bank=[(0, i, None) for i in range(4)], _exact=verify)
            result = _FastMeasuredSolve._verify_ranked(context, [2, 1, 3, 0], None, None)
        self.assertCountEqual(measured, [2, 1])
        self.assertEqual(result, [2, 1])


if __name__ == '__main__':
    unittest.main()
