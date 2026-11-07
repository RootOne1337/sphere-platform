"""Frozen causal beam v1 replay. No score tuning or independent-video claim."""
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from motor_worker.image_route_sequence import CausalSequenceBeam

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
PARAMETERS = dict(min_score=.35, peak_radius_seconds=.6, max_frame_age=.25,
                  max_observation_gap=.5, max_reference_speed=5., reference_slack_seconds=.6,
                  max_seen_sources=4096, log_margin=.2, emission_scale=3., weak_emission=-.5)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    # Seal intent before loading score arrays or computing outcome metrics.
    assert not (OUT / 'intent.json').exists(), 'Do not overwrite the first evaluation'
    intent = dict(schema='causal-sequence-beam-v1', parameters=PARAMETERS,
                  admission='fresh distinct source SHA, increasing source sequence/receipt, monotonic now; .25s max age',
                  transition='all N states, abs(reference delta)<=5*receipt_dt+.6, both directions; O(N) sliding-window maxima',
                  emission='checked score>=.35: +3score; weak checked: -.5; unchecked/excluded: 0 neutral',
                  confirmation='>=3 consecutive distinct checked-good source frames along compatible Viterbi ancestry, bounded32',
                  decision='current best must be checked-good; all-state separated runner log margin>=.2; NMS +/-.6 reference seconds',
                  unchecked='Never count neutral nodes as confirming sources. confidence_gap/uncalibrated_confidence None when runner unchecked. All-state runner still competes in margin gate.',
                  normalization='Normalized exp(max-product log states), not calibrated probability or a sum-product posterior',
                  reset='fresh accepted observation gap>.5s resets all scores/ancestry; malformed arguments reset; stale/replay does not advance scores',
                  freeze='Parameters fixed before first run; no outcome-dependent tuning',
                  module_sha256=sha(REPO / 'motor_worker/image_route_sequence.py'),
                  tests_sha256=sha(REPO / 'tests/test_image_route_sequence.py'),
                  evaluator_sha256=sha(Path(__file__).resolve()))
    save('intent.json', intent)
    inputs = [ROOT / 'scores.npz', ROOT / 'query-metrics.json', ROOT / 'reference-receipt.json',
              ROOT / 'sequence_eval/summary.json', ROOT / 'sequence_eval/events.json',
              ROOT / 'sequence_eval/final-boundary-fix/summary.json',
              ROOT / 'sequence_eval/final-boundary-fix/events.json']
    before = {str(p.relative_to(REPO)): sha(p) for p in inputs}
    save('hash-before.json', before)
    z = np.load(ROOT / 'scores.npz', allow_pickle=False)
    scores, checked, excluded = z['scores'], z['checked'], z['excluded']
    query_indices, query_ticks = z['query_indices'], z['query_ticks_90k']
    reference_indices, reference_ticks = z['reference_indices'], z['reference_ticks_90k']
    assert scores.shape == checked.shape == excluded.shape == (100, 169)
    assert checked.dtype == excluded.dtype == np.bool_ and not np.any(checked & excluded)
    assert np.isfinite(scores).all() and ((scores >= 0) & (scores <= 1)).all()
    assert np.all(np.diff(query_ticks) > 0) and np.all(np.diff(query_indices) > 0)
    query_meta = {q['query_index']: q for q in json.loads((ROOT / 'query-metrics.json').read_text())['queries']}
    refs = tuple(float(t) / 90000 for t in reference_ticks)
    for row, idx in enumerate(query_indices):
        assert query_meta[int(idx)]['ticks_90k'] == int(query_ticks[row])
    results = {}
    started = time.monotonic()
    for label, order in [('forward', list(range(100))), ('reverse', list(range(99, -1, -1)))]:
        selector = CausalSequenceBeam(refs, **PARAMETERS)
        rows = []
        started_direction = time.monotonic()
        for delivery, row in enumerate(order):
            qid = int(query_indices[row])
            # Reverse uses a new artificial ordered stream, not decreasing
            # source-frame IDs that the source-replay guard must reject.
            source_sequence = qid if label == 'forward' else delivery
            received = (int(query_ticks[row]) if label == 'forward'
                        else int(query_ticks[0]) + int(query_ticks[-1]) - int(query_ticks[row])) / 90000
            result = selector.update(scores[row].tolist(), checked=checked[row].tolist(),
                                     source_sequence=source_sequence, received_at=received, now=received,
                                     source_sha256=query_meta[qid]['bgr_sha256'])
            event = asdict(result)
            event.update(query_source_index=qid, query_ticks_90k=int(query_ticks[row]),
                         delivery_sequence=source_sequence, synthetic_received_at=received,
                         query_sha256=query_meta[qid]['bgr_sha256'],
                         candidate_source_indices=[int(reference_indices[j]) for j in result.candidate_indices],
                         same_video_time_error_seconds=None, selected_reference_source_index=None)
            if result.index is not None:
                event['selected_reference_source_index'] = int(reference_indices[result.index])
                event['same_video_time_error_seconds'] = abs(int(reference_ticks[result.index]) - int(query_ticks[row])) / 90000
                event['selected_score'] = float(scores[row, result.index])
            rows.append(event)
        chosen = [r for r in rows if r['index'] is not None]
        errors = [r['same_video_time_error_seconds'] for r in chosen]
        results[label] = dict(
            summary=dict(queries=len(rows), selected=len(chosen), selected_fraction=len(chosen) / len(rows),
                         status_counts=dict(Counter(r['status'] for r in rows)),
                         time_proxy_hits_within_0_6s=sum(e <= .6 for e in errors),
                         time_proxy_wrong_over_2s=sum(e > 2 for e in errors),
                         time_proxy_median_error_seconds=statistics.median(errors) if errors else None,
                         all_query_denominator=len(rows), abstentions_not_successes=True,
                         checked_min=min(r['checked_references'] for r in rows),
                         checked_median=statistics.median(r['checked_references'] for r in rows),
                         checked_max=max(r['checked_references'] for r in rows),
                         elapsed_seconds=time.monotonic() - started_direction),
            rows=rows)
    save('results.json', results)
    after = {str(p.relative_to(REPO)): sha(p) for p in inputs}
    assert before == after
    save('hash-after.json', after)
    summary = dict(results={k: v['summary'] for k, v in results.items()},
                   original_baseline=dict(time_proxy_hit_within_0_6s=70, high_score_wrong_over_2s=8, queries=100),
                   original_strict=dict(reference_selected=5, time_proxy_hit_within_0_6s=5, wrong_over_2s=0),
                   input_hashes_unchanged=before == after, elapsed_seconds=time.monotonic() - started,
                   intent_sha256=sha(OUT / 'intent.json'),
                   caveats='Same-video temporal labels only, not spatial ground truth or independent traversal. Synthetic zero-latency receipt clock; reverse is the same samples in a new artificial stream, not independent video. No query truth enters ranking. checked shortlist only, not all-reference verified search. Raw uncalibrated max-product masses are not probability. Neither pose nor arrival nor execution permit.')
    save('summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
