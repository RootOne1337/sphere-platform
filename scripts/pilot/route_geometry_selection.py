"""Evaluate offline camera candidates before selecting the largest component.

Scene admissibility is a reconstruction quality gate. Full-route admissibility
also requires observed temporal coverage and a stable camera trace. Neither
admits Android input, certifies road surfaces, or establishes metric accuracy.
No missing camera positions or route sections are interpolated here.
"""
from __future__ import annotations

import math

from scripts.pilot.route_motion_audit import audit

MAX_OBSERVED_GAP_SECONDS = 1.0
MAX_ENDPOINT_MISSING_SECONDS = 1.0


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def evaluate_candidate(geometry, *, selected, points, reprojection_px,
                       conditioning, intrinsics_condition, source_start, source_end):
    """Return JSON-safe measured gates; malformed inputs fail closed.

    ``source_start``/``source_end`` are actual source-video seconds, not the
    candidate's first/last registered poses. ``selected`` counts source frames
    offered to this reconstruction, allowing >=70% registration when the
    surviving observations still cover both endpoints and every time interval.
    Conditioning and intrinsics reports must come from the candidate itself.
    Call ``max(reports, key=candidate_rank)`` only after evaluating every model.
    """
    scene_reasons = []
    route_reasons = []
    cameras = geometry.get('cameras') if isinstance(geometry, dict) else None
    registered = len(cameras) if isinstance(cameras, list) else 0
    valid_selection = type(selected) is int and 10 <= selected <= 240 and registered <= selected
    coverage = registered / selected if valid_selection else None
    if not valid_selection:
        scene_reasons.append('camera_selection_invalid')
    if registered < 10 or registered > 240 or coverage is not None and coverage < .7:
        scene_reasons.append('camera_coverage_insufficient')
    if type(points) is not int or points < 300:
        scene_reasons.append('camera_points_insufficient')
    error = reprojection_px if _finite(reprojection_px) and reprojection_px >= 0 else None
    if error is None or error > 3:
        scene_reasons.append('camera_reprojection_invalid_or_large')
    if not isinstance(conditioning, dict) or conditioning.get('passed') is not True:
        scene_reasons.append('camera_geometry_degenerate')
    if not isinstance(intrinsics_condition, dict) or intrinsics_condition.get('passed') is not True:
        scene_reasons.append('camera_intrinsics_degenerate')

    motion = None
    if isinstance(cameras, list) and 2 <= registered <= 240:
        try:
            # Audit needs an image label only for human-readable diagnostics.
            # Keep measured positions/times unchanged, without modifying input.
            observed = [dict(center=camera['center'], ticks_90k=camera['ticks_90k'],
                             image=camera.get('image', f'camera-{index}'))
                        for index, camera in enumerate(cameras)]
            motion = audit(dict(cameras=observed))
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            pass
    if motion is None:
        scene_reasons.append('camera_geometry_invalid')
    else:
        if motion['rapid_reversals']:
            route_reasons.append('route_camera_reversals')
        if motion['speed_outliers']:
            route_reasons.append('route_camera_speed_outliers')

    valid_source = (_finite(source_start) and _finite(source_end)
                    and 0 <= source_start < source_end)
    coverage_report = dict(first_seconds=None, last_seconds=None,
                           missing_start_seconds=None, missing_end_seconds=None,
                           max_observed_gap_seconds=None, endpoints_observed=False,
                           all_intervals_observed=False,
                           endpoint_limit_seconds=MAX_ENDPOINT_MISSING_SECONDS,
                           interval_limit_seconds=MAX_OBSERVED_GAP_SECONDS)
    if not valid_source:
        route_reasons.append('route_source_time_invalid')
    if motion is not None:
        times = [camera['ticks_90k'] / 90000 for camera in cameras]
        maximum_gap = max(second - first for first, second in zip(times, times[1:]))
        intervals = maximum_gap <= MAX_OBSERVED_GAP_SECONDS
        coverage_report.update(first_seconds=times[0], last_seconds=times[-1],
                               max_observed_gap_seconds=maximum_gap,
                               all_intervals_observed=intervals)
        if not intervals:
            route_reasons.append('route_unobserved_interval')
        if valid_source:
            missing_start = max(0., times[0] - source_start)
            missing_end = max(0., source_end - times[-1])
            within_source = times[0] >= source_start and times[-1] <= source_end
            endpoints = (within_source and missing_start <= MAX_ENDPOINT_MISSING_SECONDS
                         and missing_end <= MAX_ENDPOINT_MISSING_SECONDS)
            coverage_report.update(missing_start_seconds=missing_start,
                                   missing_end_seconds=missing_end,
                                   endpoints_observed=endpoints)
            if not within_source:
                route_reasons.append('route_camera_outside_source')
            if not endpoints:
                route_reasons.append('route_endpoints_unobserved')
    else:
        route_reasons.append('route_camera_trace_invalid')

    scene_admissible = not scene_reasons
    return dict(schema='sphere-route-geometry-selection-v1',
                registered=registered, selected=selected if type(selected) is int else None,
                coverage=coverage, points=points if type(points) is int else None,
                reprojection_px=error, scene_admissible=scene_admissible,
                route_admissible=scene_admissible and not route_reasons,
                scene_reasons=scene_reasons, route_reasons=route_reasons,
                source_coverage=coverage_report, motion=motion,
                poses_interpolated=False, navigation_qualified=False,
                execution_qualified=False)


def candidate_rank(report):
    """Larger is better: admissibility precedes coverage, count and image error.

    Rank only reports from ``evaluate_candidate``. An inadmissible large model
    cannot outrank an admissible smaller component. A partial scene cannot
    outrank a temporally supported full route just because its error is lower.
    """
    return (report['route_admissible'], report['scene_admissible'],
            report['coverage'] if report['coverage'] is not None else -1.,
            report['registered'],
            -report['reprojection_px'] if report['reprojection_px'] is not None else -math.inf,
            report['points'] if report['points'] is not None else -1)
