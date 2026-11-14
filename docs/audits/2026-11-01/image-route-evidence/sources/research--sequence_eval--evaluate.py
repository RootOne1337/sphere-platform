"""First frozen-parameter replay, no matcher/score or product-source mutations."""
import hashlib
import json
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from motor_worker.image_route_sequence import RouteSequenceFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
if len(sys.argv) > 1:
    OUT = OUT / sys.argv[1]
    OUT.mkdir(exist_ok=True)
PARAMS = dict(min_score=.35, relative_peak=.75, peak_radius_seconds=.6,
              max_frame_age=.25, max_observation_gap=.5, max_reference_speed=5.,
              reference_slack_seconds=.6, max_seen_sources=4096)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    started = time.monotonic()
    sealed_events_sha256 = digest(OUT / 'events.json') if (OUT / 'events.json').exists() else None
    inputs = (ROOT / 'scores.npz', ROOT / 'query-metrics.json', ROOT / 'reference-receipt.json',
              REPO / 'motor_worker/image_route_sequence.py',
              REPO / 'tests/test_image_route_sequence.py')
    before = {str(p.relative_to(REPO)): digest(p) for p in inputs}
    raw = np.load(inputs[0], allow_pickle=False)
    scores, checked = raw['scores'], raw['checked']
    query_indices, ticks = raw['query_indices'], raw['query_ticks_90k']
    reference_indices, reference_ticks = raw['reference_indices'], raw['reference_ticks_90k']
    assert scores.shape == checked.shape == (100, 169)
    assert checked.dtype == np.bool_ and np.isfinite(scores).all()
    assert ((scores >= 0) & (scores <= 1)).all()
    assert np.all(np.diff(query_indices) > 0) and np.all(np.diff(ticks) > 0)
    query_meta = json.loads(inputs[1].read_text())['queries']
    meta_by_index = {q['query_index']: q for q in query_meta}
    refs = tuple(float(t) / 90000 for t in reference_ticks)
    query_times = ticks.astype(float) / 90000
    for i, qid in enumerate(query_indices):
        assert meta_by_index[int(qid)]['ticks_90k'] == int(ticks[i])
    # The constructor and calls receive no expected reference index or absolute
    # query-to-reference time offset. Synthetic receipt deltas are the only
    # query-time input; proxy labels are evaluated after the returned result.
    reports = {}
    rows = {}
    count = len(scores)
    order = list(range(count))
    shuffled = order.copy()
    random.Random(20261101).shuffle(shuffled)
    controls = {
        'causal_source_order': order,
        'artificial_abrupt_block_reorder': order[:25] + order[50:75] + order[25:50] + order[75:],
        'artificial_shuffled_source_order_seed_20261101': shuffled,
    }
    for name, source_order in controls.items():
        selector = RouteSequenceFilter(refs, **PARAMS)
        events = []
        baseline = []
        for delivery, row in enumerate(source_order):
            query_index = int(query_indices[row])
            sequence = query_index if name == 'causal_source_order' else delivery
            received = float(query_times[delivery])
            result = selector.update(scores[row].tolist(), checked=checked[row].tolist(),
                                     source_sequence=sequence, received_at=received, now=received,
                                     source_sha256=meta_by_index[query_index]['bgr_sha256'])
            payload = asdict(result)
            payload.update(query_index=query_index, source_sequence=sequence,
                           synthetic_received_at=received, query_ticks_90k=int(ticks[row]))
            if result.index is not None:
                payload['reference_source_index'] = int(reference_indices[result.index])
                payload['same_video_time_error_seconds'] = abs(refs[result.index] - query_times[row])
                payload['selected_score'] = float(scores[row, result.index])
            else:
                payload['same_video_time_error_seconds'] = None
            events.append(payload)
            valid = np.flatnonzero(checked[row])
            best = int(valid[np.argmax(scores[row, valid])]) if len(valid) else None
            if best is not None and scores[row, best] > 0:
                error = abs(int(reference_ticks[best]) - int(ticks[row])) / 90000
                baseline.append(dict(error=float(error), score=float(scores[row, best])))
        selected = [e for e in events if e['index'] is not None]
        errors = [e['same_video_time_error_seconds'] for e in selected]
        reports[name] = dict(
            queries=count, status_counts=dict(Counter(e['status'] for e in events)),
            selected_count=len(selected), selected_fraction=len(selected) / count,
            selected_time_proxy_within_0_6s=sum(e <= .6 for e in errors),
            selected_time_proxy_wrong_over_2s=sum(e > 2 for e in errors),
            selected_time_proxy_median_error_seconds=statistics.median(errors) if errors else None,
            baseline_top1_positive_count=len(baseline),
            baseline_top1_time_proxy_within_0_6s=sum(e['error'] <= .6 for e in baseline),
            baseline_top1_high_score_wrong_over_2s=sum(e['error'] > 2 and e['score'] >= .35 for e in baseline),
            unknown_and_ambiguous_are_abstentions_not_successes=True,
            artificial_reorder_control=name != 'causal_source_order',
        )
        rows[name] = events
    after = {str(p.relative_to(REPO)): digest(p) for p in inputs}
    assert before == after
    summary = dict(parameters_fixed_before_first_metrics=PARAMS, results=reports,
                   inputs_sha256=before, inputs_unchanged=before == after,
                   actual_query_sha_proof='SHA256 of exact decoded source BGR from query-metrics.json; JPEG previews not hashed as source',
                   receipt_clock='Synthetic zero-latency source-PTS receipt timeline, not measured live delivery',
                   interpretation='Same-source temporal labels are a retrieval proxy, not spatial or independent traversal ground truth. Reorder controls are synthetic and not independent video. Unchecked references are untested; verified search only covers the producer shortlist. No pose, arrival, or execution qualification.',
                   elapsed_seconds=time.monotonic() - started,
                   first_events_sha256=sealed_events_sha256,
                   receipt_recovery_note='First replay wrote all events, then JSON summary failed on numpy int64; serialization-only repair reran identical fixed parameters and asserts byte-identical events.' if sealed_events_sha256 else None)
    (OUT / 'events.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    assert sealed_events_sha256 is None or digest(OUT / 'events.json') == sealed_events_sha256
    output = json.dumps(summary, indent=2, default=lambda value: value.item())
    (OUT / 'summary.json').write_text(output, encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
