import numpy as np
import pytest

from scripts.pilot.route_epipolar_diagnostic import epipolar_residuals


def views():
    camera = np.array([[500., 0., 320.], [0., 500., 180.], [0., 0., 1.]])
    first = np.column_stack((np.eye(3), np.zeros(3)))
    second = np.column_stack((np.eye(3), [-1., 0., 0.]))
    world = np.array([[x, y, 5.+.2*x] for x in range(4) for y in range(3)], dtype=float)
    def project(ext):
        projected = (world @ ext[:, :3].T + ext[:, 3]) @ camera.T
        return projected[:, :2] / projected[:, 2, None]
    return camera, first, second, project(first), project(second)


def test_static_camera_pair_uses_true_correspondences_not_training_scores():
    camera, first, second, a, b = views()
    clean = epipolar_residuals(camera, camera, first, second, a, b)
    shifted = epipolar_residuals(camera, camera, first, second, a, b + [0, 8])
    assert clean is not None and np.max(clean) < 1e-9
    assert shifted is not None and np.median(shifted) > 5


def test_pure_rotation_or_no_translation_is_unknown_not_a_zero_error():
    camera, first, _, a, b = views()
    assert epipolar_residuals(camera, camera, first, first, a, b) is None


def test_bad_camera_and_nonfinite_tracks_are_not_treated_as_evidence():
    camera, first, second, a, b = views()
    bad = first.copy(); bad[0, 0] = 2
    with pytest.raises(ValueError, match='rotation_invalid'):
        epipolar_residuals(camera, camera, bad, second, a, b)
    a[0, 0] = np.nan
    with pytest.raises(ValueError, match='input_invalid'):
        epipolar_residuals(camera, camera, first, second, a, b)
