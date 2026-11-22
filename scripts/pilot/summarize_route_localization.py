"""Summarize same-recording localization without running inference or device input.

Timestamp agreement is a sanity check against the recorded camera sequence,
not metric ground truth: stationary scenes and revisited locations can alias.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def summarize(report, route):
    if (report.get('schema') != 'sphere-route-localization-quality-v1'
            or report.get('same_capture') is not True
            or report.get('capture_manifest_sha256') != route.get('source_capture_sha256')
            or report.get('route_id') != route.get('id')
            or report.get('physical_actions') != 0
            or report.get('execution_qualified') is not False):
        raise ValueError('same_recording_binding_required')
    times, samples = route.get('source_seconds'), report.get('samples')
    if (not isinstance(times, list) or len(times) < 2 or not isinstance(samples, list)
            or len(samples) > 3000):
        raise ValueError('route_localization_data_invalid')
    if any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in times):
        raise ValueError('route_reference_time_invalid')
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('route_reference_time_invalid')
    counts, reasons, bins = Counter(), Counter(), {}
    agreements = []
    last_time, last_index = -1., -1
    for sample in samples:
        timestamp, index, pose = sample.get('media_seconds'), sample.get('source_index'), sample.get('pose')
        if (type(timestamp) not in (int, float) or not math.isfinite(timestamp)
                or timestamp < 0 or timestamp <= last_time
                or type(index) is not int or index <= last_index or not isinstance(pose, dict)):
            raise ValueError('route_sample_invalid')
        last_time, last_index = timestamp, index
        state, reason = pose.get('state'), pose.get('reason')
        if state not in {'localized', 'confirming', 'unknown'} or not isinstance(reason, str):
            raise ValueError('route_sample_invalid')
        counts[state] += 1
        if state == 'unknown':
            reasons[reason] += 1
        key = math.floor(timestamp / 5) * 5
        row = bins.setdefault(key, dict(start_seconds=key, localized=0, confirming=0, unknown=0))
        row[state] += 1
        segment = pose.get('segment')
        if state != 'unknown':
            if type(segment) is not int or not 0 <= segment < len(times) - 1:
                raise ValueError('route_sample_segment_invalid')
            # Distance to the recorded segment's source-time interval in seconds.
            offset = max(times[segment] - timestamp, 0., timestamp - times[segment + 1])
            agreements.append(dict(seconds=timestamp, segment_start_seconds=times[segment],
                                   segment_end_seconds=times[segment + 1], time_offset_seconds=offset,
                                   state=state))
        elif segment is not None:
            raise ValueError('unknown_pose_must_not_claim_segment')
    offsets = sorted(row['time_offset_seconds'] for row in agreements)
    def percentile(fraction):
        if not offsets:
            return None
        at = (len(offsets) - 1) * fraction
        left, right = math.floor(at), math.ceil(at)
        return offsets[left] + (offsets[right] - offsets[left]) * (at - left)
    return dict(schema='sphere-same-recording-localization-summary-v1',
        sample_count=len(samples), counts=dict(counts), unknown_reasons=dict(reasons),
        bins=[bins[key] for key in sorted(bins)],
        timestamp_sanity=dict(confirmed_or_confirming=len(offsets), median_seconds=percentile(.5),
            p95_seconds=percentile(.95), maximum_seconds=max(offsets) if offsets else None,
            over_2_seconds=sum(value > 2 for value in offsets)),
        same_recording=True, timing_is_not_position_ground_truth=True, metric_scale_known=False,
        independent_session_tested=False, android_to_model_latency_known=False,
        physical_actions=0, execution_qualified=False, agreements=agreements)


def read_bounded(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('route_localization_input_invalid')
    return path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('report', 'route', 'receipt', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('exclusive_output_required')
    route_bytes = read_bounded(args.route, 32 * 1024**2)
    receipt = json.loads(read_bounded(args.receipt, 1024**2))
    if hashlib.sha256(route_bytes).hexdigest() != receipt.get('sha256'):
        raise ValueError('route_hash_mismatch')
    report_bytes = read_bounded(args.report, 16 * 1024**2)
    result = summarize(json.loads(report_bytes), json.loads(route_bytes))
    result['source_report_sha256'] = hashlib.sha256(report_bytes).hexdigest()
    result['source_route_sha256'] = receipt['sha256']
    write_json(args.output, result)
    print(json.dumps({key: result[key] for key in ('sample_count', 'counts', 'unknown_reasons', 'timestamp_sanity')}))


if __name__ == '__main__':
    main()
