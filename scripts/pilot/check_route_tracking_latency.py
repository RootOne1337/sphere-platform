"""Wall-clock, latest-only comparison on held-out saved RGB; no Android input.

Unlike the synthetic-clock cost probe, this permits background work to complete
on the actual receiver clock. Old source frames are skipped instead of queued.
It tests processing latency and pose agreement, not a closed-loop game drive.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import uuid


def run(job, output, *, count=64, start=4., candidate_limit=3, recovery_candidate_limit=None,
        native_threads=(1, 4), kinds=('synchronous', 'background')):
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    runtime = initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np
    from motor_worker.browser_teach import decoded_browser, validate_browser
    from motor_worker.policy import PolicyFrame
    from motor_worker.route_background_tracking import BackgroundVerifiedRouteLocalizer
    from motor_worker.route_localization import SparseRoute
    from motor_worker.route_tracking import AnchoredRouteLocalizer
    from motor_worker.walk_route import WalkRouteFollower
    from scripts.pilot.check_route_localization_cost import private_bytes
    from scripts.pilot.resource_guard import windows_memory

    root, job, output = Path.cwd().resolve(), Path(job).resolve(), Path(output).resolve()
    if (not job.is_relative_to(root/'.local-pilot/reconstruction-jobs')
            or not output.is_relative_to(root/'.local-pilot') or output.exists()
            or not 24 <= count <= 96 or not 0 <= start <= 60
            or type(candidate_limit) is not int or not 3 <= candidate_limit <= 8
            or not native_threads or any(type(v) is not int or v not in (1, 4) for v in native_threads)
            or not kinds or any(k not in ('synchronous', 'background') for k in kinds)):
        raise ValueError('tracking_latency_scope')
    if windows_memory()['availableRamBytes'] < 4.75*1024**3:
        raise RuntimeError('tracking_latency_memory_guard')
    active = json.loads((job/'navigation/active.json').read_bytes())['id']
    receipt = json.loads((job/'navigation'/active/'receipt.json').read_bytes())
    paths = [job/'geometry.json', job/'input/manifest.json', job/'navigation'/active/'route.json']
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    route = SparseRoute.load(paths[-1], sha256=receipt['sha256'])
    route = replace(route, profile=replace(route.profile, width=960, height=540,
                    excluded=(*route.profile.excluded, (.33, .45, .67, 1.))))
    queries, last = [], -1.
    for row, image in decoded_browser(validate_browser(job/'input')):
        seconds = row['relative_ticks_90k']/90000
        if seconds < start or seconds-last < .095 or row['index'] in route.source_frame_indices:
            continue
        rgb = cv.resize(image.to_ndarray(format='rgb24'), (960, 540), interpolation=cv.INTER_AREA)
        ok, jpeg = cv.imencode('.jpg', cv.cvtColor(rgb, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError('query_jpeg')
        queries.append((row['index'], seconds, jpeg.tobytes()))
        last = seconds
        if len(queries) == count:
            break
    if len(queries) != count:
        raise ValueError('tracking_latency_query_coverage')
    cases = []
    for threads in native_threads:
        cv.setNumThreads(threads)
        for kind, cls in (('synchronous', AnchoredRouteLocalizer), ('background', BackgroundVerifiedRouteLocalizer)):
            if kind not in kinds:
                continue
            if windows_memory()['availableRamBytes'] < 4.75*1024**3:
                raise RuntimeError('tracking_latency_memory_guard')
            cv.setRNGSeed(7)
            epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
            tracker = cls(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal,
                          candidate_limit=candidate_limit, recovery_candidate_limit=recovery_candidate_limit)
            follower = WalkRouteFollower(route, clock=time.monotonic, start_mode='recognized_route')
            rows, at, skipped, next_at = [], 0, 0, 0.
            before = private_bytes()
            cpu, wall = time.process_time(), time.monotonic()
            try:
                while at < len(queries):
                    due = wall+queries[at][1]-queries[0][1]
                    delay = max(due, next_at)-time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    elapsed = time.monotonic()-wall
                    while at+1 < len(queries) and queries[at+1][1]-queries[0][1] <= elapsed:
                        at += 1
                        skipped += 1
                    next_at = time.monotonic()+.05  # Same maximum 20 Hz as the browser.
                    index, seconds, jpeg = queries[at]
                    began = time.perf_counter()
                    bgr = cv.imdecode(np.frombuffer(jpeg, np.uint8), cv.IMREAD_COLOR)
                    rgb = cv.cvtColor(bgr, cv.COLOR_BGR2RGB).tobytes()
                    frame = PolicyFrame(epoch, at+1, time.monotonic(), 960, 540, rgb)
                    pose = tracker.observe(frame, episode_id=episode, goal_revision=goal, scene='active')
                    plan = follower.observe(pose)
                    rows.append(dict(sourceIndex=index, sourceSeconds=seconds, method=tracker.last_diagnostic['method'],
                        pose=pose.state, reason=pose.reason, plan=plan['phase'], inliers=pose.inliers,
                        center=pose.center, rotation=pose.rotation, wallMs=(time.perf_counter()-began)*1000,
                        backgroundAccepted=tracker.last_diagnostic.get('backgroundAccepted', False),
                        backgroundSubmitted=tracker.last_diagnostic.get('backgroundSubmitted', False)))
                    at += 1
            finally:
                if hasattr(tracker, 'close'):
                    tracker.close(wait=True)
            core_seconds, seconds = time.process_time()-cpu, time.monotonic()-wall
            times = [r['wallMs'] for r in rows]
            fast = [r['wallMs'] for r in rows if r['method'] == 'map_anchored_flow']
            case = dict(kind=kind, nativeThreads=threads, rows=rows, skipped=skipped,
                localized=sum(r['pose'] == 'localized' for r in rows),
                backgroundAccepted=sum(r['backgroundAccepted'] for r in rows),
                wallMs=dict(p50=float(np.median(times)), p95=float(np.percentile(times, 95)), maximum=max(times)),
                flowMs=None if not fast else dict(p50=float(np.median(fast)), p95=float(np.percentile(fast, 95)), maximum=max(fast)),
                cpuCoreSeconds=core_seconds, wallSeconds=seconds, averageCpuCores=core_seconds/seconds,
                privateBytesBeforeQueries=before, privateBytesAfterQueries=private_bytes())
            cases.append(case)
            print(json.dumps({k: v for k, v in case.items() if k != 'rows'}), flush=True)
    agreements = []
    for threads in native_threads:
        paired = [c for c in cases if c['nativeThreads'] == threads]
        if len(paired) != 2:
            continue
        first, second = paired
        indexed = {r['sourceIndex']: r for r in first['rows'] if r['pose'] == 'localized'}
        deltas, turns = [], []
        for row in second['rows']:
            old = indexed.get(row['sourceIndex'])
            if old is not None and row['pose'] == 'localized':
                deltas.append(float(np.linalg.norm(np.array(row['center'])-old['center'])))
                r, s = np.array(row['rotation']).reshape(3, 3), np.array(old['rotation']).reshape(3, 3)
                turns.append(float(np.arccos(np.clip((np.trace(r@s.T)-1)/2, -1, 1))))
        agreements.append(dict(nativeThreads=threads, commonLocalizedFrames=len(deltas),
            centerDifferenceUnitsP95=None if not deltas else float(np.percentile(deltas, 95)),
            rotationDifferenceRadiansP95=None if not turns else float(np.percentile(turns, 95))))
    result = dict(schema='sphere-route-tracking-latency-v1', cpuRuntime=runtime,
        physicalActions=0, queryFramesHeldOut=True, syntheticSourceClock=False, latestOnly=True,
        durationClock='perf_counter', receiverClock='monotonic', minimumObservationIntervalSeconds=.05,
        candidateLimit=candidate_limit, recoveryCandidateLimit=recovery_candidate_limit,
        independentGameplay=False, feedbackLoop=False, includes=['JPEG_decode', 'localization', 'planner'],
        excludes=['HTTP', 'browser', 'stream', 'Android', 'GPU_reconstruction'], sourceHashes=hashes,
        sourceUnchanged=all(hashlib.sha256((root/p).read_bytes()).hexdigest() == h for p, h in hashes.items()),
        agreements=agreements, cases=cases)
    with output.open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=64)
    parser.add_argument('--start', type=float, default=4.)
    parser.add_argument('--candidate-limit', type=int, default=3)
    parser.add_argument('--recovery-candidate-limit', type=int)
    parser.add_argument('--native-threads', type=int, nargs='+', choices=(1, 4), default=(1, 4))
    parser.add_argument('--kinds', nargs='+', choices=('synchronous', 'background'), default=('synchronous', 'background'))
    args = parser.parse_args()
    result = run(args.job, args.output, count=args.count, start=args.start, candidate_limit=args.candidate_limit,
                 recovery_candidate_limit=args.recovery_candidate_limit,
                 native_threads=tuple(args.native_threads), kinds=tuple(args.kinds))
    print(json.dumps(dict(agreements=result['agreements'], sourceUnchanged=result['sourceUnchanged'])))
