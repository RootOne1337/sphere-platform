"""Offline HUD-to-camera motion consistency; no metric or navigation claim."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


def analyze(geometry, samples, source_frames, *, max_gap_seconds=0.2, trusted_edges=None):
    """Integrate only consecutive accepted, source-bound readings spanning an edge.

    trusted_edges is a collection of zero-based camera-edge indices. If omitted,
    the median is fit on the evaluated data and is not an independent check.
    """
    if isinstance(max_gap_seconds, bool) or not isinstance(max_gap_seconds, (int, float)) or not math.isfinite(max_gap_seconds) or not 0 < max_gap_seconds <= 1:
        raise ValueError('invalid_max_gap')
    source = {}
    previous = -1
    for frame in source_frames:
        index, tick = frame['index'], frame['relative_ticks_90k']
        if type(index) is not int or index < 0 or index in source or type(tick) is not int or tick <= previous:
            raise ValueError('invalid_source_frames')
        source[index] = tick
        previous = tick
    values = []
    previous_index = previous_tick = -1
    for sample in samples:
        index, tick, status = sample['frame_index'], sample['relative_ticks_90k'], sample['status']
        if type(index) is not int or type(tick) is not int or index <= previous_index or tick <= previous_tick or source.get(index) != tick:
            raise ValueError('invalid_sample_binding_or_order')
        if status not in ('accepted', 'unknown'):
            raise ValueError('invalid_sample_status')
        speed = sample.get('hud_kmh')
        if status == 'accepted' and (type(speed) not in (int, float) or not math.isfinite(speed) or speed < 0):
            raise ValueError('invalid_accepted_speed')
        if status == 'unknown' and speed is not None:
            raise ValueError('unknown_speed_must_be_null')
        values.append((index, tick, speed))
        previous_index, previous_tick = index, tick
    cameras = geometry['cameras']
    if len(cameras) < 2:
        raise ValueError('insufficient_cameras')
    points, ticks = [], []
    for camera in cameras:
        tick, center = camera['ticks_90k'], camera['center']
        try:
            index = int(Path(camera['image']).stem)
        except (KeyError, ValueError, TypeError):
            raise ValueError('invalid_camera_binding') from None
        if type(tick) is not int or source.get(index) != tick or (ticks and tick <= ticks[-1]) or len(center) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in center):
            raise ValueError('invalid_camera_binding_or_position')
        ticks.append(tick); points.append(center)
    if trusted_edges is not None:
        trusted_edges = set(trusted_edges)
        if any(type(i) is not int or not 0 <= i < len(cameras)-1 for i in trusted_edges):
            raise ValueError('invalid_trusted_edges')
    edges = []
    for i, (start, end) in enumerate(zip(ticks, ticks[1:])):
        distance = math.dist(points[i], points[i+1])
        if not math.isfinite(distance):
            raise ValueError('camera_distance_overflow')
        edge = dict(edge_index=i, first_image=cameras[i]['image'], second_image=cameras[i+1]['image'], start_ticks_90k=start, end_ticks_90k=end, interval_seconds=(end-start)/90000, camera_step_units=distance, hud_distance=None, implied_scale=None, relative_to_fit=None, status='unknown', reason=None)
        cursor, total = start, 0.0
        for left, right in zip(values, values[1:]):
            lt, rt = left[1], right[1]
            if rt <= cursor or lt >= end:
                continue
            if lt > cursor or left[2] is None or right[2] is None or (rt-lt)/90000 > max_gap_seconds:
                edge['reason'] = 'unbracketed_or_unknown_or_gap'; break
            stop = min(end, rt)
            v0 = left[2] + (right[2]-left[2]) * (cursor-lt)/(rt-lt)
            v1 = left[2] + (right[2]-left[2]) * (stop-lt)/(rt-lt)
            total += (v0+v1)*0.5/3.6 * (stop-cursor)/90000
            cursor = stop
            if cursor == end:
                break
        if cursor != end:
            edge['reason'] = edge['reason'] or 'unbracketed_or_unknown_or_gap'
        elif not math.isfinite(total):
            raise ValueError('hud_integration_overflow')
        else:
            edge['hud_distance'] = total
            if total == 0:
                edge['status'] = 'zero_hud_distance'; edge['reason'] = 'scale_undefined_at_zero_speed'
            else:
                ratio = distance/total
                if not math.isfinite(ratio):
                    raise ValueError('scale_overflow')
                edge['status'] = 'accepted'; edge['implied_scale'] = ratio
        edges.append(edge)
    fit = [e['implied_scale'] for e in edges if e['status'] == 'accepted' and e['implied_scale'] > 0 and (trusted_edges is None or e['edge_index'] in trusted_edges)]
    scale = statistics.median(fit) if len(fit) >= 20 else None
    for edge in edges:
        if edge['status'] == 'accepted' and scale is not None:
            relative = edge['implied_scale']/scale
            if not math.isfinite(relative):
                raise ValueError('relative_scale_overflow')
            edge['relative_to_fit'] = relative
            edge['classification'] = 'scale_outlier_review' if relative > 4 or relative < .25 else 'consistent_with_fit'
        else:
            edge['classification'] = 'unknown'
    return dict(schema='sphere-hud-camera-consistency-v1', edges=edges, fit_edge_count=len(fit), fit_scope='same_data' if trusted_edges is None else 'caller_selected_trusted_subset', sfm_units_per_hud_distance=scale, minimum_fit_edges=20, scale_outlier_factor=4, diagnostic_only=True, independent_accuracy_verified=False, navigation_qualified=False, distance_units='integrated_game_hud_kmh_divided_by_3.6', limitation='Camera motion may differ from vehicle motion; no metric or ground truth claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from motor_worker.browser_teach import validate_browser
    capture = validate_browser(args.capture)
    geometry_bytes = args.geometry.read_bytes()
    sample_bytes = args.samples.read_bytes()
    manifest_hash = hashlib.sha256(capture.originals['manifest.json']).hexdigest()
    geometry = json.loads(geometry_bytes)
    if geometry.get('source_manifest_sha256') != manifest_hash:
        raise ValueError('geometry_source_mismatch')
    receipt = json.loads(Path(str(args.samples)+'.receipt.json').read_bytes())
    if receipt.get('source_manifest_sha256') != manifest_hash or receipt.get('output_csv_sha256') != hashlib.sha256(sample_bytes).hexdigest():
        raise ValueError('sample_receipt_mismatch')
    with args.samples.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    samples = [dict(frame_index=int(row['frame_index']), relative_ticks_90k=int(row['relative_ticks_90k']), hud_kmh=float(row['hud_kmh']) if row['hud_kmh'] else None, status=row['status']) for row in rows]
    report = analyze(geometry, samples, capture.frames)
    report.update(source_manifest_sha256=manifest_hash, geometry_sha256=hashlib.sha256(geometry_bytes).hexdigest(), sample_csv_sha256=hashlib.sha256(sample_bytes).hexdigest())
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps(dict(fit_edge_count=report['fit_edge_count'], sfm_units_per_hud_distance=report['sfm_units_per_hud_distance'])))


if __name__ == '__main__':
    main()
