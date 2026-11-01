"""Missing runtime support must have measured causes, without changing gates."""
from collections import defaultdict

import numpy as np

from scripts.pilot.route_landmark_builder import build, triangulate


def scene(depth=10., baseline=.5):
    K = np.array([[500., 0., 480.], [0., 500., 270.], [0., 0., 1.]])
    matrices = [np.column_stack((np.eye(3), [-i * baseline, 0., 0.])) for i in range(3)]
    pixels = []
    for matrix in matrices:
        projection = K @ (matrix @ np.array([0., 0., depth, 1.]))
        pixels.append(np.array([projection[:2] / projection[2]]))
    return K, matrices, pixels


def test_wrong_camera_side_is_distinct_from_insufficient_parallax():
    for depth, baseline, reason in [(-10., .5, 'nonpositive_depth'),
                                     (100., .001, 'parallax_under_1_degree')]:
        K, matrices, pixels = scene(depth, baseline)
        reasons = defaultdict(int)
        assert triangulate([(i, 0) for i in range(3)], pixels, matrices, K, rejected=reasons) is None
        assert reasons == {reason: 1}


def test_inconsistent_observations_are_not_silently_reported_as_too_few_points():
    K, matrices, pixels = scene()
    pixels[1][0, 1] += 30.
    reasons = defaultdict(int)
    assert triangulate([(i, 0) for i in range(3)], pixels, matrices, K, rejected=reasons) is None
    assert reasons == {'reprojection_over_3px': 1}


def test_build_accounts_for_every_rejected_track_without_reclassifying_accepted_points():
    K, matrices, pixels = scene()
    # Orthogonal descriptors are mutual, unique matches in all three views.
    desc = np.zeros((2, 128), dtype=np.float32)
    desc[0, 0] = 1.; desc[1, 1] = 1.
    observations = [(np.vstack((xy, xy + [0., 40.])), desc.copy()) for xy in pixels]
    observations[-1][0][1, 1] += 30.
    accepted, report = build(observations, matrices, K, checkpoint=lambda: None)
    assert len(accepted) == report['accepted'] == 1
    assert report['tracks'] == 2 and report['rejected'] == 1
    assert report['rejection_reasons'] == {'reprojection_over_3px': 1}
    assert sum(report['rejection_reasons'].values()) == report['rejected']
    assert np.allclose(accepted[0][1], [0., 0., 10.])
