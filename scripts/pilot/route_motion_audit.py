"""Read-only temporal diagnostics of recovered camera poses, never motion commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def audit(geometry):
    cameras = geometry['cameras']
    if not 2 <= len(cameras) <= 240:
        raise ValueError('camera_count_invalid')
    positions, times = [], []
    for camera in cameras:
        center, tick = camera['center'], camera['ticks_90k']
        if (len(center) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in center)
                or type(tick) is not int or tick < 0 or times and tick <= times[-1]):
            raise ValueError('camera_time_or_position_invalid')
        positions.append(center)
        times.append(tick)
    vectors = [[b[i] - a[i] for i in range(3)] for a, b in zip(positions, positions[1:])]
    steps = [math.hypot(*row) for row in vectors]
    intervals = [(b - a) / 90000 for a, b in zip(times, times[1:])]
    rates = [step / seconds for step, seconds in zip(steps, intervals)]
    length = sum(steps)
    if any(not math.isfinite(v) for v in [*steps, *rates, length]):
        raise ValueError('camera_motion_overflow')
    median = statistics.median(steps)
    median_rate = statistics.median(rates)
    reversals = []
    for i in range(1, len(vectors)):
        if min(steps[i - 1], steps[i]) <= max(1e-9, median * .5) or times[i + 1] - times[i - 1] > 2 * 90000:
            continue
        cosine = sum((a / steps[i - 1]) * (b / steps[i]) for a, b in zip(vectors[i - 1], vectors[i]))
        if cosine < -.5:
            reversals.append(dict(view=i + 1, image=cameras[i]['image'], seconds=times[i] / 90000))
    # Registration gaps have a larger distance even at constant velocity. Compare
    # distance per actual source time, never raw steps or an assumed fixed FPS.
    # This only flags discontinuities for review; a real camera cut can trigger it.
    outliers = []
    if len(rates) >= 5 and median_rate > 1e-9:
        for i, rate in enumerate(rates):
            if rate > 8 * median_rate:
                outliers.append(dict(view=i + 2, image=cameras[i + 1]['image'],
                    seconds=times[i + 1] / 90000, interval_seconds=intervals[i],
                    median_rate_ratio=rate / median_rate))
    return dict(schema='sphere-camera-temporal-audit-v1', views=len(cameras),
        first_seconds=times[0] / 90000, last_seconds=times[-1] / 90000,
        path_units=length, endpoint_displacement_units=math.dist(positions[0], positions[-1]),
        median_step_units=median, max_step_units=max(steps), rapid_reversals=reversals,
        median_rate_units_per_second=median_rate, speed_outliers=outliers,
        warning='poses_require_temporal_review' if len(reversals) >= 3 or outliers else None,
        heuristic_only=True, metric_scale=None, navigation_qualified=False,
        interpretation='Camera motion may include head bob, camera effects or reconstruction error; no automatic correction.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.geometry.is_symlink() or args.geometry.stat().st_size > 16 * 1024**2 or args.output.exists():
        raise ValueError('audit_input_or_exclusive_output_invalid')
    body = args.geometry.read_bytes()
    report = audit(json.loads(body))
    report['geometry_sha256'] = hashlib.sha256(body).hexdigest()
    write_json(args.output, report)
    print(json.dumps(dict(views=report['views'], reversals=len(report['rapid_reversals']), warning=report['warning'])))


if __name__ == '__main__':
    main()
