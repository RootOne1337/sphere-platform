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


@pytest.mark.parametrize('case', ['clock', 'nonfinite'])
def test_invalid_time_or_position_is_not_presented_as_movement(case):
    source = geometry([0, 1, 2])
    if case == 'clock':
        source['cameras'][1]['ticks_90k'] = 0
    else:
        source['cameras'][1]['center'][0] = float('nan')
    with pytest.raises(ValueError, match='time_or_position'):
        audit(source)
