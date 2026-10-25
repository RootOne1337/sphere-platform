"""Reject numerically valid but meaningless geometry and blurred reference views."""
import pytest

from scripts.pilot.reconstruction_quality import reference_quality, sparse_condition


def test_zero_depth_cloud_rejected_even_with_tiny_reprojection_error():
    pytest.importorskip('numpy')
    cameras = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]
    bad = [[0, 0, 1e-8], [1, 0, 1e-8], [1, 2, 3]]
    result = sparse_condition(cameras, bad)
    assert result['near_camera_points'] == 2 and not result['passed']
    shifted = sparse_condition([[x * 100 + 200, y, z] for x, y, z in cameras],
                               [[x * 100 + 200, y * 100, z * 100] for x, y, z in bad])
    assert shifted['near_camera_fraction'] == result['near_camera_fraction']


def test_finite_supported_cloud_and_invalid_path():
    pytest.importorskip('numpy')
    assert sparse_condition([[0, 0, 0], [1, 0, 0]], [[0, 0, 2], [2, 3, 4]])['passed']
    with pytest.raises(ValueError, match='path_degenerate'):
        sparse_condition([[0, 0, 0], [0, 0, 0]], [[0, 0, 2]])


def metrics(values):
    return dict(schema='sphere-reference-render-evaluation-v1', training=False, held_out=False,
                resolution_limit=960, views=[dict(psnr=p, ssim=s) for p, s in values])


def test_average_does_not_hide_a_broken_route_section():
    result = reference_quality(metrics([(30, .92), (30, .92), (13.3, .58)]))
    assert result['state'] == 'rejected'
    assert reference_quality(metrics([(24, .81), (23, .8), (22, .78)]))['state'] == 'passed'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '30'])
def test_invalid_metrics_cannot_qualify_a_scene(value):
    with pytest.raises(ValueError, match='nonfinite_or_invalid'):
        reference_quality(metrics([(24, .8), (24, .8), (value, .8)]))
