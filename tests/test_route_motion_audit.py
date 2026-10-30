import pytest

from scripts.pilot.route_motion_audit import audit


def geometry(positions):
    return dict(cameras=[dict(image=f'{i:08}.png', center=[x, 0, 0], ticks_90k=i * 45000)
                         for i, x in enumerate(positions)])


def test_straight_motion_is_not_flagged_and_stays_nonmetric():
    report = audit(geometry([0, 1, 2, 3]))
    assert report['path_units'] == report['endpoint_displacement_units'] == 3
    assert report['warning'] is None
    assert report['navigation_qualified'] is False
    assert report['metric_scale'] is None


def test_oscillating_poses_are_reported_without_smoothing_or_navigation_acceptance():
    source = geometry([0, 2, 0, 2, 0, 2, 0])
    report = audit(source)
    assert len(report['rapid_reversals']) == 5
    assert report['warning'] == 'poses_require_temporal_review'
    assert report['heuristic_only'] is True
    assert source['cameras'][1]['center'] == [2, 0, 0]


def test_a_stationary_camera_does_not_divide_by_zero():
    assert audit(geometry([0, 0, 0]))['rapid_reversals'] == []


def test_forward_jump_is_flagged_even_without_reversals():
    source = geometry([0, 1, 2, 3, 4, 34, 35, 36])
    report = audit(source)
    assert report['rapid_reversals'] == []
    assert report['warning'] == 'poses_require_temporal_review'
    assert report['speed_outliers'] == [dict(view=6, image='00000005.png', seconds=2.5,
        interval_seconds=.5, median_rate_ratio=30)]
    assert report['navigation_qualified'] is False
    assert source['cameras'][5]['center'] == [34, 0, 0]


def test_long_registration_gap_is_not_mistaken_for_a_velocity_jump():
    source = geometry([0, 1, 2, 3, 4, 34, 35, 36])
    for camera in source['cameras']:
        camera['ticks_90k'] = camera['center'][0] * 45000
    report = audit(source)
    assert report['speed_outliers'] == []
    assert report['warning'] is None
    assert report['median_rate_units_per_second'] == 2


def test_velocity_jump_diagnostic_is_invariant_to_reconstruction_scale():
    ratios = []
    for scale in [.01, 1, 100]:
        report = audit(geometry([scale * v for v in [0, 1, 2, 3, 4, 34, 35, 36]]))
        ratios.append(report['speed_outliers'][0]['median_rate_ratio'])
    assert ratios == pytest.approx([30, 30, 30])


@pytest.mark.parametrize('case', ['clock', 'nonfinite', 'boolean'])
def test_invalid_time_or_position_is_not_presented_as_movement(case):
    source = geometry([0, 1, 2])
    if case == 'clock':
        source['cameras'][1]['ticks_90k'] = 0
    elif case == 'nonfinite':
        source['cameras'][1]['center'][0] = float('nan')
    else:
        source['cameras'][1]['center'][0] = True
    with pytest.raises(ValueError, match='time_or_position'):
        audit(source)


def test_finite_coordinates_with_overflowing_deltas_are_rejected():
    with pytest.raises(ValueError, match='motion_overflow'):
        audit(geometry([-1e308, 1e308, 0]))


def test_overflowing_path_sum_cannot_be_written_as_json_infinity():
    source = geometry([0, 5e307, 0, 5e307, 0])
    for i, camera in enumerate(source['cameras']):
        camera['ticks_90k'] = i * 90000
    with pytest.raises(ValueError, match='motion_overflow'):
        audit(source)


def test_direction_diagnostic_does_not_overflow_for_large_finite_units():
    report = audit(geometry([0, 1e200, 0, 1e200, 0, 1e200, 0]))
    assert len(report['rapid_reversals']) == 5
