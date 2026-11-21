"""Read-only timing analysis of bounded browser route reports.

All intervals use one browser clock. Android uptime and browser time are never
subtracted. A native acknowledgement is input application, not world motion.
The source-frame sequence and native-input sequence are different namespaces;
these logs cannot prove frame-to-Android latency by joining their numbers.
"""
from __future__ import annotations

import math
from collections import Counter


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(count=0, p50=None, p95=None, maximum=None)

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return dict(count=len(ordered), p50=percentile(.5), p95=percentile(.95), maximum=ordered[-1])


def summarize_reactivity(report):
    """Report observed tails and missing evidence without a readiness verdict."""
    if not isinstance(report, dict):
        raise ValueError('route_reactivity_report')
    observations, native = report.get('observations', []), report.get('nativeInputs', [])
    if (not isinstance(observations, list) or not isinstance(native, list)
            or len(observations) > 18000 or len(native) > 4096
            or any(not isinstance(row, dict) for row in [*observations, *native])):
        raise ValueError('route_reactivity_quota')
    total = report.get('observationCount')
    if total is not None and (type(total) is not int or total < len(observations)):
        raise ValueError('route_reactivity_count')
    # The browser can decimate observations or retain a rolling tail. Never
    # interpret a sparse retained stream as the original acquisition cadence.
    coverage = ('incomplete' if total is not None and total > len(observations)
                else 'complete_by_counter' if total is not None else 'unknown')
    times = [row.get('elapsedMs') for row in observations]
    if any(not _number(value) for value in times) or any(a > b for a, b in zip(times, times[1:])):
        raise ValueError('route_reactivity_observation_clock')
    for row in observations:
        for name in ('ageMs', 'computeMs'):
            if name in row and not _number(row[name]):
                raise ValueError('route_reactivity_observation_clock')
    usable = [row for row in observations if row.get('poseState') == 'localized'
              and row.get('state') == 'following' and _number(row.get('ageMs')) and row['ageMs'] < 250]
    correction_gaps = [b['elapsedMs'] - a['elapsedMs'] for a, b in zip(usable, usable[1:])]

    def input_key(row):
        fields = ('sequence', 'gesture', 'action', 'pointer_id')
        if any(type(row.get(field)) is not int for field in fields):
            return None
        return tuple(row[field] for field in fields)

    submitted, receipts = {}, {}
    for row in native:
        key = input_key(row)
        if key is None or not _number(row.get('at_ms')):
            continue
        target = submitted if row.get('stage') == 'submitted' else receipts if row.get('stage') == 'receipt' else None
        if target is not None:
            target.setdefault(key, []).append(row)
    ack_ms, ambiguous, unmatched, rejected = [], 0, 0, Counter()
    for key, rows in receipts.items():
        starts = submitted.get(key, [])
        if len(rows) != 1 or len(starts) > 1:
            ambiguous += len(rows)
            continue
        row = rows[0]
        if not starts or row['at_ms'] < starts[0]['at_ms']:
            unmatched += 1
            continue
        if row.get('outcome') == 'applied':
            ack_ms.append(row['at_ms'] - starts[0]['at_ms'])
        else:
            rejected[str(row.get('outcome', 'unknown'))] += 1

    return dict(schema='sphere-route-reactivity-v1', executionQualified=False,
        analysisPhysicalActions=0, fullAndroidLatencyKnown=False,
        timing='single_browser_clock', observationsRetained=len(observations),
        observationCount=total, observationCoverage=coverage,
        sourceFrameToReplyMs=_distribution([row['ageMs'] for row in observations if 'ageMs' in row]),
        backendComputeMs=_distribution([row['computeMs'] for row in observations if 'computeMs' in row]),
        freshFollowingCorrections=len(usable), retainedCorrectionGapMs=_distribution(correction_gaps),
        correctionCadenceQualified=False,
        nativeSubmitToAppliedAckMs=_distribution(ack_ms), nativeReceiptsUnmatched=unmatched,
        nativeReceiptsAmbiguous=ambiguous, nativeRejectedOutcomes=dict(rejected),
        limitations=['retained_samples_may_be_decimated_or_tail_only',
                     'no_query_to_native_command_correlation',
                     'no_android_capture_or_world_motion_latency',
                     'ack_is_not_distance_or_route_completion'])
