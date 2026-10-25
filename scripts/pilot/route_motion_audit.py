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
        if (len(center) != 3 or any(not math.isfinite(v) for v in center)
                or type(tick) is not int or tick < 0 or times and tick <= times[-1]):
            raise ValueError('camera_time_or_position_invalid')
        positions.append(center)
        times.append(tick)
    vectors = [[b[i] - a[i] for i in range(3)] for a, b in zip(positions, positions[1:])]
    steps = [math.sqrt(sum(v * v for v in row)) for row in vectors]
    median = statistics.median(steps)
    reversals = []
    for i in range(1, len(vectors)):
        if min(steps[i - 1], steps[i]) <= max(1e-9, median * .5) or times[i + 1] - times[i - 1] > 2 * 90000:
            continue
        cosine = sum(a * b for a, b in zip(vectors[i - 1], vectors[i])) / (steps[i - 1] * steps[i])
        if cosine < -.5:
            reversals.append(dict(view=i + 1, image=cameras[i]['image'], seconds=times[i] / 90000))
    return dict(schema='sphere-camera-temporal-audit-v1', views=len(cameras),
        first_seconds=times[0] / 90000, last_seconds=times[-1] / 90000,
        path_units=sum(steps), endpoint_displacement_units=math.dist(positions[0], positions[-1]),
        median_step_units=median, max_step_units=max(steps), rapid_reversals=reversals,
        warning='poses_require_temporal_review' if len(reversals) >= 3 else None,
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
