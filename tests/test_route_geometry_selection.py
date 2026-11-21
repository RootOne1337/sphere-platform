import copy
import json

import pytest

from scripts.pilot.route_geometry_selection import candidate_rank, evaluate_candidate


def geometry(times=None, positions=None):
    times = [i * .5 for i in range(14)] if times is None else times
    positions = times if positions is None else positions
    return dict(cameras=[dict(image=f'{index:08}.png', ticks_90k=round(time * 90000),
                              center=[position, 0., 0.])
                         for index, (time, position) in enumerate(zip(times, positions))])


def evaluate(value=None, **overrides):
    kwargs = dict(selected=20, points=500, reprojection_px=1.,
                  conditioning=dict(passed=True), intrinsics_condition=dict(passed=True),
                  source_start=0., source_end=6.5)
    kwargs.update(overrides)
    return evaluate_candidate(geometry() if value is None else value, **kwargs)


def test_complete_healthy_route_accepts_seventy_percent_without_interpolation():
    source = geometry()
    before = copy.deepcopy(source)
    result = evaluate(source)
    assert result['coverage'] == .7
    assert result['scene_admissible'] and result['route_admissible']
    assert result['scene_reasons'] == result['route_reasons'] == []
    assert result['source_coverage']['endpoints_observed']
    assert result['source_coverage']['all_intervals_observed']
    assert not result['poses_interpolated'] and not result['execution_qualified']
    assert source == before
    json.dumps(result, allow_nan=False)


def test_collapsed_full_count_cannot_outrank_clean_smaller_route():
    collapsed = evaluate(geometry([i * 6.5 / 19 for i in range(20)]),
                         conditioning=dict(passed=False), reprojection_px=.01)
    clean = evaluate()
    assert not collapsed['scene_admissible'] and not collapsed['route_admissible']
    assert 'camera_geometry_degenerate' in collapsed['scene_reasons']
    assert max([collapsed, clean], key=candidate_rank) is clean


def test_missing_tail_remains_partial_scene_and_loses_to_complete_route():
    partial = evaluate(source_end=8.)
    complete = evaluate()
    assert partial['scene_admissible'] and not partial['route_admissible']
    assert partial['source_coverage']['missing_end_seconds'] == 1.5
    assert 'route_endpoints_unobserved' in partial['route_reasons']
    assert candidate_rank(complete) > candidate_rank(partial)


def test_interior_gap_is_not_hidden_by_matching_endpoints_or_registration_fraction():
    times = [0, .5, 1, 1.5, 2, 2.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5]
    result = evaluate(geometry(times), source_end=7.5)
    assert result['scene_admissible'] and not result['route_admissible']
    assert result['source_coverage']['endpoints_observed']
    assert result['source_coverage']['max_observed_gap_seconds'] == 1.5
    assert 'route_unobserved_interval' in result['route_reasons']


def test_one_second_endpoint_and_interior_limits_are_inclusive():
    times = [1 + i for i in range(14)]
    result = evaluate(geometry(times), source_end=15.)
    assert result['route_admissible']
    assert result['source_coverage']['missing_start_seconds'] == 1.
    assert result['source_coverage']['missing_end_seconds'] == 1.
    assert result['source_coverage']['max_observed_gap_seconds'] == 1.


def test_one_rapid_reversal_requires_review_even_when_audit_warning_is_none():
    positions = [0, .5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 5.5]
    result = evaluate(geometry(positions=positions))
    assert result['scene_admissible'] and not result['route_admissible']
    assert result['motion']['warning'] is None
    assert 'route_camera_reversals' in result['route_reasons']


def test_camera_speed_outlier_requires_review():
    positions = [i * .5 for i in range(7)] + [20 + i * .5 for i in range(7)]
    result = evaluate(geometry(positions=positions))
    assert not result['route_admissible']
    assert 'route_camera_speed_outliers' in result['route_reasons']


@pytest.mark.parametrize('override, reason', [
    (dict(points=299), 'camera_points_insufficient'),
    (dict(points=True), 'camera_points_insufficient'),
    (dict(reprojection_px=3.01), 'camera_reprojection_invalid_or_large'),
    (dict(reprojection_px=float('nan')), 'camera_reprojection_invalid_or_large'),
    (dict(reprojection_px=float('inf')), 'camera_reprojection_invalid_or_large'),
    (dict(reprojection_px=10 ** 500), 'camera_reprojection_invalid_or_large'),
    (dict(reprojection_px=-1.), 'camera_reprojection_invalid_or_large'),
    (dict(reprojection_px=True), 'camera_reprojection_invalid_or_large'),
    (dict(conditioning=dict(passed=1)), 'camera_geometry_degenerate'),
    (dict(intrinsics_condition=dict(passed=False)), 'camera_intrinsics_degenerate'),
    (dict(selected=21), 'camera_coverage_insufficient'),
    (dict(selected=True), 'camera_selection_invalid'),
    (dict(selected=13), 'camera_selection_invalid'),
])
def test_basic_quality_gates_fail_closed(override, reason):
    result = evaluate(**override)
    assert not result['scene_admissible'] and not result['route_admissible']
    assert reason in result['scene_reasons']
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('changes', [
    dict(source_start=float('nan')), dict(source_end=float('inf')),
    dict(source_end=10 ** 500),
    dict(source_start=True), dict(source_end=0), dict(source_start=-1),
])
def test_invalid_actual_source_window_cannot_admit_route(changes):
    result = evaluate(**changes)
    assert result['scene_admissible'] and not result['route_admissible']
    assert 'route_source_time_invalid' in result['route_reasons']
    json.dumps(result, allow_nan=False)


def test_camera_outside_source_is_not_clamped_into_valid_coverage():
    result = evaluate(source_start=.1)
    assert not result['route_admissible']
    assert 'route_camera_outside_source' in result['route_reasons']


@pytest.mark.parametrize('value', [None, {}, dict(cameras=[]), dict(cameras=[{}] * 14)])
def test_malformed_camera_geometry_is_a_rejection(value):
    result = evaluate_candidate(value, selected=20, points=500, reprojection_px=1.,
                                conditioning=dict(passed=True), intrinsics_condition=dict(passed=True),
                                source_start=0., source_end=6.5)
    assert not result['scene_admissible'] and not result['route_admissible']
    assert 'camera_geometry_invalid' in result['scene_reasons']


def test_nonfinite_or_out_of_order_measured_poses_cannot_win():
    for key, value in [('center', [float('nan'), 0, 0]), ('ticks_90k', 0)]:
        source = geometry()
        source['cameras'][4][key] = value
        result = evaluate(source)
        assert not result['route_admissible']
        assert candidate_rank(evaluate()) > candidate_rank(result)
        json.dumps(result, allow_nan=False)
