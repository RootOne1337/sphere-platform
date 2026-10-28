"""Disambiguate repeated scenery with every intervening source-video frame.

Only existing feature matches supported by forward/backward optical tracks
survive. No poses are interpolated and no source image/database is modified.
The destination is a separate, exclusive SQLite database for geometric testing.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def flow_supported_matches(matches, source_ids, tracked, valid, destination, *, scale, tolerance=3.):
    """Require the exact feature identity and its observed endpoint, not a lookalike."""
    import numpy as np

    pairs = np.asarray(matches, dtype=np.uint32).reshape(-1, 2)
    if not len(pairs) or not len(source_ids):
        return pairs[:0]
    lookup = {int(identity): index for index, identity in enumerate(source_ids)}
    selected = np.array([lookup.get(int(pair[0]), -1) for pair in pairs])
    safe = np.maximum(selected, 0)
    if (pairs[:, 1] >= len(destination)).any():
        raise ValueError('temporal_match_feature_index')
    endpoints = (destination[pairs[:, 1], :2] - .5) * scale
    supported = ((selected >= 0) & valid[safe]
                 & (np.linalg.norm(tracked[safe] - endpoints, axis=1) <= tolerance))
    return pairs[supported]


def filter_video_matches(job, prepared, source_database, output, check, *, max_lag=2, timeout=300,on_progress=None):
    import cv2
    import numpy as np
    import pycolmap as p
    from motor_worker.browser_teach import decoded_browser, validate_browser

    job, prepared, source_database, output = map(Path, (job, prepared, source_database, output))
    if max_lag not in (1, 2, 3, 5, 8) or output.exists() or source_database.is_symlink():
        raise ValueError('temporal_match_exclusive_output')
    check()
    capture = validate_browser(job / 'input')
    provenance = json.loads((prepared / 'reconstruction-input.json').read_bytes())
    if provenance.get('source_manifest_sha256') != hashlib.sha256((job/'input/manifest.json').read_bytes()).hexdigest():
        raise ValueError('temporal_match_source_binding')
    rows = provenance['images']
    if not 10 <= len(rows) <= 240:
        raise ValueError('temporal_match_view_quota')
    by_name = {Path(row['image']).name: row for row in rows}
    width, height = capture.geometry
    scale = min(1., 960 / max(width, height))
    size = (round(width * scale), round(height * scale))
    cv2.setNumThreads(2)
    features, proposals, starts = {}, {}, {}
    with p.Database.open(source_database) as db:
        images = sorted(db.read_all_images(), key=lambda image: image.name)
        if len(images) != len(rows) or any(image.name not in by_name for image in images):
            raise ValueError('temporal_match_source_binding')
        for i, image in enumerate(images):
            features[image.image_id] = db.read_keypoints(image.image_id)
            starts[by_name[image.name]['source_index']] = i
            for j in range(i + 1, min(i + max_lag + 1, len(images))):
                second = images[j]
                if db.exists_matches(image.image_id, second.image_id):
                    proposals[i, j] = db.read_matches(image.image_id, second.image_id)
    if len(starts) != len(images) or any(capture.frames[index]['relative_ticks_90k'] != by_name[images[i].name]['relative_ticks_90k'] for index, i in starts.items()):
        raise ValueError('temporal_match_time_binding')
    # SQLite backup includes a completed source WAL without copying inconsistent files.
    with sqlite3.connect(source_database.resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(output) as dst:
            src.backup(dst)
    with p.Database.open(output) as db:
        db.clear_matches()
        db.clear_two_view_geometries()
    active, results, previous = [], [], None
    began, last_check, decoded = time.monotonic(), 0., 0
    for row, frame in decoded_browser(capture):
        now = time.monotonic()
        if now - began > timeout:
            raise RuntimeError('temporal_match_timeout')
        if now - last_check > 3:
            check()
            if on_progress is not None:
                on_progress(decoded,len(capture.frames))
            last_check = now
        gray = cv2.resize(frame.to_ndarray(format='gray'), size, interpolation=cv2.INTER_AREA)
        if active and previous is not None:
            counts = [len(group['points']) for group in active]
            points = np.concatenate([group['points'] for group in active]).astype('float32').reshape(-1, 1, 2)
            moved, status, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None, winSize=(21, 21), maxLevel=3)
            back, backward, _ = cv2.calcOpticalFlowPyrLK(gray, previous, moved, None, winSize=(21, 21), maxLevel=3)
            valid = (status.ravel().astype(bool) & backward.ravel().astype(bool)
                     & np.isfinite(moved).all(axis=(1, 2))
                     & (np.linalg.norm(back - points, axis=2).ravel() <= 1.))
            at = 0
            for group, count in zip(active, counts, strict=True):
                keep=group['valid'] & valid[at:at+count]
                group['points'] = moved[at:at+count, 0][keep]
                group['ids'] = group['ids'][keep]
                group['valid'] = np.ones(int(keep.sum()), dtype=bool)
                at += count
            active=[group for group in active if len(group['points'])]
        selected = starts.get(row['index'])
        if selected is not None:
            with p.Database.open(output) as db:
                for group in active:
                    key = (group['index'], selected)
                    matches = proposals.get(key)
                    if matches is None:
                        continue
                    first, second = images[group['index']], images[selected]
                    kept = flow_supported_matches(matches, group['ids'], group['points'], group['valid'],
                                                  features[second.image_id], scale=scale)
                    if len(kept) >= 15:
                        db.write_matches(first.image_id, second.image_id, kept)
                    results.append(dict(first=first.name, second=second.name, proposed=len(matches),
                                        supported=len(kept), written=len(kept) >= 15))
            active = [group for group in active if selected - group['index'] < max_lag]
            wanted = [pairs[:, 0] for (i, _), pairs in proposals.items() if i == selected and len(pairs)]
            if wanted:
                ids = np.unique(np.concatenate(wanted))
                if len(ids) > 8192 or (ids >= len(features[images[selected].image_id])).any():
                    raise ValueError('temporal_match_track_quota')
                points = (features[images[selected].image_id][ids, :2] - .5) * scale
                active.append(dict(index=selected, ids=ids, points=points,
                                   valid=np.ones(len(ids), dtype=bool)))
        previous = gray
        decoded += 1
    if decoded != len(capture.frames):
        raise ValueError('temporal_match_decode_incomplete')
    if on_progress is not None:
        on_progress(decoded,len(capture.frames))
    report = dict(schema='sphere-temporal-route-matches-v1', decodedFrames=decoded,
                  sourceViews=len(images), maxLag=max_lag, trackingResolution=list(size),
                  forwardBackwardPixels=1., destinationTolerancePixels=3.,
                  seconds=time.monotonic()-began, pairs=results,
                  physicalActions=0, posesInterpolated=False, sourceModified=False)
    write_json(output.with_suffix('.temporal.json'), report)
    return report
