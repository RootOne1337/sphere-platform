"""Read-only, source-bound image-sequence review; never navigation authority."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from pathlib import Path

HASH = re.compile(r'^[0-9a-f]{64}$')


def _parse(raw):
    def bad(_):
        raise ValueError('image_route_review_nonfinite')
    return json.loads(raw, parse_constant=bad)


def _bytes(path, root, maximum):
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('image_route_review_path')
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('image_route_review_quota')
    data = path.read_bytes()
    if len(data) > maximum:
        raise ValueError('image_route_review_quota')
    return data


def _score(value):
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def read_image_route_review(job: Path):
    """Return validated JSON bytes bound to the job's sealed source index."""
    job = Path(job)
    if job.is_symlink():
        raise ValueError('image_route_review_path')
    root = job.resolve(strict=True)
    source, folder = job / 'input', job / 'image-route-review'
    for path in (source, folder):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('image_route_review_path')
    manifest_raw = _bytes(source / 'manifest.json', root, 65536)
    frames_raw = _bytes(source / 'frames.jsonl', root, 16 * 1024**2)
    receipt_raw = _bytes(folder / 'receipt.json', root, 4096)
    body = _bytes(folder / 'review.json', root, 256 * 1024)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    frames_sha = hashlib.sha256(frames_raw).hexdigest()
    manifest, receipt, data = _parse(manifest_raw), _parse(receipt_raw), _parse(body)
    if (not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict)
            or not isinstance(manifest['files'].get('frames.jsonl'), dict)
            or manifest['files']['frames.jsonl'].get('sha256') != frames_sha):
        raise ValueError('image_route_review_source_index_binding')
    if (not isinstance(receipt, dict)
            or set(receipt) - {'schema', 'scope', 'execution_qualified', 'source_manifest_sha256', 'review_sha256', 'frames_sha256'}
            or receipt.get('schema') != 'sphere-image-route-review-receipt-v1'
            or receipt.get('scope') != 'DIAGNOSTIC_ONLY' or receipt.get('execution_qualified') is not False
            or receipt.get('source_manifest_sha256') != manifest_sha
            or receipt.get('review_sha256') != hashlib.sha256(body).hexdigest()
            or ('frames_sha256' in receipt and receipt['frames_sha256'] != frames_sha)):
        raise ValueError('image_route_review_receipt_binding')
    if (not isinstance(data, dict)
            or set(data) != {'schema','scope','source_manifest_sha256','position_confirmed','arrival_confirmed',
                             'execution_qualified','reference_ticks_90k','samples'}
            or data['schema'] != 'sphere-image-route-review-v1' or data['scope'] != 'OFFLINE_SAME_RECORDING'
            or data['source_manifest_sha256'] != manifest_sha or not HASH.fullmatch(manifest_sha)
            or data['position_confirmed'] is not False or data['arrival_confirmed'] is not False
            or data['execution_qualified'] is not False):
        raise ValueError('image_route_review_invalid')
    frames = []
    for line in io.BytesIO(frames_raw):
        if not line.strip():
            raise ValueError('image_route_review_frames_invalid')
        if len(frames) >= 36000:
            raise ValueError('image_route_review_frame_quota')
        frame = _parse(line)
        if (not isinstance(frame, dict) or type(frame.get('index')) is not int or frame['index'] != len(frames)
                or type(frame.get('relative_ticks_90k')) is not int or frame['relative_ticks_90k'] < 0
                or frames and frame['relative_ticks_90k'] <= frames[-1]):
            raise ValueError('image_route_review_frames_invalid')
        frames.append(frame['relative_ticks_90k'])
    refs, samples = data['reference_ticks_90k'], data['samples']
    if (not isinstance(refs, list) or not 2 <= len(refs) <= 256
            or any(type(v) is not int or v < 0 for v in refs)
            or any(a >= b for a, b in zip(refs, refs[1:])) or not set(refs).issubset(frames)):
        raise ValueError('image_route_review_references_invalid')
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1024:
        raise ValueError('image_route_review_samples_invalid')
    seen = set(); reference_set = set(refs)
    required = {'source_index','ticks_90k','raw_reference_ticks_90k','raw_score',
                'sequence_reference_ticks_90k','sequence_status'}
    for sample in samples:
        if (not isinstance(sample, dict) or not required <= sample.keys()
                or set(sample) - required - {'sequence_score'}):
            raise ValueError('image_route_review_sample_invalid')
        idx, tick = sample['source_index'], sample['ticks_90k']
        raw, selected, status = sample['raw_reference_ticks_90k'], sample['sequence_reference_ticks_90k'], sample['sequence_status']
        if (type(idx) is not int or not 0 <= idx < len(frames) or idx in seen
                or type(tick) is not int or frames[idx] != tick
                or (raw is not None and (type(raw) is not int or raw not in reference_set))
                or not _score(sample['raw_score'])
                or status not in ('reference_selected','ambiguous','unknown','stale')
                or (selected is not None and (type(selected) is not int or selected not in reference_set))
                or (status == 'reference_selected') != (selected is not None)
                or ('sequence_score' in sample and not _score(sample['sequence_score']))):
            raise ValueError('image_route_review_sample_invalid')
        seen.add(idx)
    return body
