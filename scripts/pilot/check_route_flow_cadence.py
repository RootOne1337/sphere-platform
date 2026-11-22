"""Measure how far one verified map seed survives on a held-out recording."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime


def run(job, source, queries, seed_index):
    initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np

    from motor_worker.browser_teach import decoded_browser, validate_browser
    from motor_worker.route_localization import (
        SIZE,
        RouteLocalizer,
        extract_gray_features,
    )
    from motor_worker.route_tracking import AnchoredRouteLocalizer
    from scripts.pilot.check_vehicle_start_replay import checked_frame
    from scripts.pilot.route_descriptor_attachment import load_descriptor_recovery
    from scripts.pilot.route_guided_descriptor_probe import refine_descriptor_pose
    from scripts.pilot.route_workspace import RouteWorkspaces

    queries = queries.resolve(strict=True)
    cv.setNumThreads(1)
    active = job / 'navigation/active.json'
    active_bytes = active.read_bytes()
    nav = active.parent / json.loads(active_bytes)['id']
    receipt = json.loads((nav / 'receipt.json').read_bytes())
    route, _, _ = load_descriptor_recovery(nav, receipt, stamp=RouteWorkspaces._runtime_source_stamp)
    if route is None:
        raise ValueError('descriptor_attachment_unavailable')
    binding = {key: str(uuid.uuid4()) for key in ('capture_epoch', 'episode_id', 'goal_revision')}
    localizer = AnchoredRouteLocalizer(route, **binding)

    capture = validate_browser(source)
    manifest = json.loads((queries / 'manifest.json').read_bytes())
    query = next((item for item in manifest['captures'] if item['capture_id'] == capture.manifest['id']), None)
    with (source / 'video.h264').open('rb') as stream:
        source_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (query is None or source_sha != query['video_sha256']
            or hashlib.sha256(capture.originals['manifest.json']).hexdigest() != query['manifest_sha256']
            or manifest['jpeg'] != {'width': SIZE[0], 'height': SIZE[1], 'quality': 86}):
        raise ValueError('replay_source_mismatch')
    if capture.manifest['id'] == json.loads((job / 'input/manifest.json').read_bytes())['id']:
        raise ValueError('cadence_requires_independent_capture')
    sampled = {item['frame_index']: item for item in query['frames']}
    if seed_index not in sampled:
        raise ValueError('cadence_seed_not_sampled')
    start_tick = sampled[seed_index]['relative_ticks_90k']
    images = []
    for row, decoded in decoded_browser(capture):
        index = row['index']
        age = (row['relative_ticks_90k'] - start_tick) / 90000
        if age < 0:
            continue
        if age >= localizer.MAX_DESCRIPTOR_AGE:
            break
        if len(images) >= 60:
            raise ValueError('cadence_frame_budget')
        rgb = cv.resize(decoded.to_ndarray(format='rgb24'), SIZE, interpolation=cv.INTER_AREA)
        ok, encoded = cv.imencode('.jpg', cv.cvtColor(rgb, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 86])
        if not ok or (index in sampled and encoded.tobytes() != checked_frame(queries, sampled[index])):
            raise ValueError('replay_jpeg_mismatch')
        gray = cv.cvtColor(cv.imdecode(encoded, cv.IMREAD_COLOR), cv.COLOR_BGR2GRAY)
        images.append((index, age, gray))
    if len(images) < 2 or images[0][0] != seed_index:
        raise ValueError('cadence_seed_or_window_missing')

    gray = images[0][2]
    xy, descriptors = extract_gray_features(gray, localizer.mask)
    cv.setRNGSeed(17)
    seed = RouteLocalizer._solve(localizer, xy, descriptors)
    if seed is None:
        raise ValueError('cadence_seed_not_verified')
    seed = refine_descriptor_pose(localizer, seed, xy, descriptors)
    if localizer._nearest(seed[0]) is None:
        raise ValueError('cadence_seed_off_route')

    def measure(native, refresh):
        center, rotation, _, _, ids, pixels = seed
        previous = localizer._nearest(center)
        previous_age = 0.0
        localizer._anchors = gray, pixels.astype(np.float32).reshape(-1, 1, 2), ids
        rows = []

        def consistent_position(solution, age):
            if solution is None:
                return None
            near = localizer._nearest(solution[0])
            limit = localizer._motion_limit(previous[1], age - previous_age)
            angle = float(np.arccos(np.clip((np.trace(solution[1] @ rotation.T) - 1) / 2, -1, 1)))
            if (near is None or np.linalg.norm(solution[0] - center) > limit or angle > 1.05
                    or abs(near[1] - previous[1]) > limit):
                return None
            return near

        for index, age, current in images[1:]:
            if not native and index not in sampled:
                continue
            # Try across a short miss within the seed age cap. Never publish
            # a stale pose or replace the anchor when this attempt fails.
            if age - previous_age >= 0.45:
                break
            localizer._gray = current
            localizer.last_diagnostic = {}
            cv.setRNGSeed(17)
            began = time.perf_counter()
            solution = localizer._flow()
            near = consistent_position(solution, age)
            inliers = solution[2] if solution is not None else 0
            if near is not None:
                if refresh:
                    xy, descriptors = extract_gray_features(current, localizer.mask)
                    enriched = refine_descriptor_pose(localizer, solution, xy, descriptors)
                    enriched_position = consistent_position(enriched, age)
                    if enriched_position is not None:
                        solution, near = enriched, enriched_position
                center, rotation, _, _, ids, pixels = solution
                previous, previous_age = near, age
                localizer._anchors = current, pixels.astype(np.float32).reshape(-1, 1, 2), ids
            rows.append(dict(index=index, age=age, archived=index in sampled,
                             flowRetained=localizer.last_diagnostic.get('flowRetained', 0),
                             pnpInliers=inliers, refreshedInliers=solution[2] if near is not None else None,
                             consistent=near is not None, elapsedMs=(time.perf_counter()-began)*1000))
        return dict(native=native, refresh=refresh, lastConsistentAge=previous_age, rows=rows)

    cases = [measure(native, refresh) for native in (False, True) for refresh in (False, True)]
    if active.read_bytes() != active_bytes:
        raise RuntimeError('route_selection_changed_during_replay')
    return dict(schema='sphere-route-flow-cadence-probe-v1', physicalActions=0,
                executionQualified=False, geometry=receipt['geometry_sha256'], videoSha256=source_sha,
                seedIndex=seed_index, seedTicks90k=start_tick, seedInliers=seed[2], cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--queries', type=Path, required=True)
    parser.add_argument('--seed-index', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    private = (Path.cwd() / '.local-pilot').resolve()
    output = args.output.resolve()
    if not output.is_relative_to(private) or output.exists():
        parser.error('output must be a new file under .local-pilot')
    result = run(args.job, args.source, args.queries, args.seed_index)
    with output.open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
