"""Recorded vehicle frames through an isolated HTTP handler; never sends input.

This is open-loop diagnostic evidence, not an Android/browser transport test
or proof that a vehicle can follow the route. Only the report is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import secrets
import shutil
import threading
import time
from collections import Counter
from contextlib import closing
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from scripts.pilot.check_route_full_replay import file_sha, observation_timing, query_provenance
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime


def copy_checked(source, target, root, hashes):
    """Copy regular files only; never follow links or silently change a source."""
    for path in (source, *source.parents):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('fixture_link')
        if path == root:
            break
    if not source.is_file() or not source.resolve().is_relative_to(root):
        raise ValueError('fixture_source')
    before = file_sha(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    if file_sha(target) != before or file_sha(source) != before:
        raise ValueError('fixture_source_changed')
    hashes[str(source.relative_to(root))] = before


def run(job, output, *, diagnostic=None, holdout=None, from_seconds=0, max_seconds=15,
        start_mode='beginning'):
    initialize_route_cpu_runtime()
    from motor_worker.browser_teach import validate_browser, decoded_browser
    from motor_worker.route_reference_lk import ReferenceLKRoute
    from scripts.pilot.resource_guard import windows_memory
    from scripts.pilot.route_diagnostic_video import validate_diagnostic_video, decoded_diagnostic_video
    from scripts.pilot.route_preparation_source import attempt_cancelled, attempt_source, public_source

    root = Path.cwd().resolve()
    pilot = root / '.local-pilot'
    job, output = Path(job).resolve(strict=True), Path(output).resolve()
    if (job.parent != pilot / 'reconstruction-jobs' or output.exists()
            or not output.is_relative_to(pilot) or output == pilot
            or output.is_relative_to(pilot / 'reconstruction-jobs')
            or output.is_relative_to(job) or job.is_relative_to(output)
            or not math.isfinite(from_seconds) or not math.isfinite(max_seconds)
            or not 0 <= from_seconds <= max_seconds - 1 or max_seconds > 55
            or (diagnostic is not None and holdout is not None)
            or start_mode not in ('beginning', 'recognized_route')
            or windows_memory()['availableRamBytes'] < 4.75 * 1024**3):
        raise ValueError('vehicle_replay_scope_or_resources')
    active = json.loads((job / 'navigation/active.json').read_bytes())['id']
    nav = job / 'navigation' / active
    selected = attempt_source(job, nav)
    if (selected['binding'] is None or selected['binding']['kind'] != 'alternative'
            or selected['binding']['runtime_family'] != 'reference_lk' or attempt_cancelled(job, nav)):
        raise ValueError('vehicle_replay_requires_active_reference_lk')
    expected = public_source(selected)
    reference = validate_browser(job / 'input')
    query_hashes = {}
    if diagnostic:
        paths = tuple(Path(p).resolve(strict=True) for p in diagnostic)
        if any(not p.is_relative_to(pilot) for p in paths):
            raise ValueError('vehicle_replay_diagnostic_scope')
        capture = validate_diagnostic_video(*paths)
        query_hashes = {path: file_sha(path) for path in paths}
        frames = decoded_diagnostic_video(capture, max_seconds=max_seconds)
        query = dict(kind='diagnostic_video', videoSha256=capture.video_sha256,
                     metadataSha256=capture.metadata_sha256, indexSha256=capture.metadata['indexSha256'],
                     declaredJob=capture.metadata['job'],
                     declaredGeometrySha256=capture.metadata.get('geometrySha256'),
                     independentGameplayUnverified=True)
        excluded = set()
    else:
        query_path = Path(holdout).resolve(strict=True) if holdout else job / 'input'
        if not query_path.is_relative_to(pilot):
            raise ValueError('vehicle_replay_holdout_scope')
        capture = validate_browser(query_path) if holdout else reference
        frames = decoded_browser(capture)
        receipt = json.loads((nav / 'receipt.json').read_bytes())
        with closing(ReferenceLKRoute.load(nav / 'route.json', sha256=receipt['sha256'])) as route:
            query, excluded = query_provenance(reference, capture, route.source_frame_indices)
        query_hashes = {path: file_sha(path) for path in (query_path / 'video.h264', query_path / 'frames.jsonl',
                                                          query_path / 'manifest.json')}
    if capture.geometry[0] * reference.geometry[1] != capture.geometry[1] * reference.geometry[0]:
        raise ValueError('vehicle_replay_aspect_mismatch')
    alternative = selected['binding']['alternative_id']
    # Explicit finite source trees; large reconstruction databases are excluded.
    sources = [job / 'control.json', job / 'state.json', job / 'navigation/active.json',
               job / 'prepared/reconstruction-input.json']
    for directory in (job / 'input', nav, job / 'alternatives' / alternative):
        for path in directory.rglob('*'):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('fixture_link')
            if path.is_file():
                sources.append(path)
    if len(sources) > 1000 or sum(p.stat().st_size for p in sources) > 1024**3:
        raise ValueError('fixture_copy_quota')
    output.mkdir(parents=True)
    if shutil.disk_usage(output).free < 2 * 1024**3:
        raise ValueError('vehicle_replay_disk_reserve')
    hashes = {}
    with TemporaryDirectory(prefix='fixture-', dir=output) as fixture, closing(frames):
        identity, key = secrets.token_hex(16), secrets.token_hex(32)
        target = Path(fixture) / identity
        for source in sources:
            copy_checked(source, target / source.relative_to(job), job, hashes)
        rows, skipped = replay_http(target, key, active, expected, capture.geometry, frames, excluded,
                                    from_seconds, max_seconds, start_mode)
    if any(file_sha(job / name) != sha for name, sha in hashes.items()):
        raise RuntimeError('vehicle_replay_source_changed')
    if any(file_sha(path) != sha for path, sha in query_hashes.items()):
        raise RuntimeError('vehicle_replay_query_changed')
    report = dict(schema='sphere-vehicle-http-replay-v1', physicalActions=0, openLoop=True,
                  browserTransportTested=False, liveServiceUsed=False, arrivalProven=False,
                  motionFeedback=False, source=expected, sourceUnchanged=True, sourceHashes=hashes,
                  query=query, windowSeconds=[from_seconds, max_seconds], excludedReferenceFrames=len(excluded),
                  observations=len(rows), skippedLate=skipped,
                  poseCounts=dict(Counter(row['pose']['state'] for row in rows)),
                  planReasons=dict(Counter(row['vehicle']['reason'] for row in rows)), samples=rows)
    (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def replay_http(target, key, active, expected, geometry, frames, excluded, from_seconds, max_seconds, start_mode):
    import cv2 as cv
    from scripts.pilot.reconstruction_service import BoundedServer, Jobs, handler

    control_path = target / 'control.json'
    control = json.loads(control_path.read_bytes())
    control['key_sha256'] = hashlib.sha256(key.encode()).hexdigest()
    control_path.write_text(json.dumps(control), encoding='utf-8')
    # The original cancellation fence is inode-bound. The new fixture has no
    # parent CANCEL and receives its own equivalent baseline, never a hardlink.
    intent_path = target / 'navigation' / active / 'intent.json'
    intent = json.loads(intent_path.read_bytes())
    intent['cancellationPolicy']['parentCancelAtIntent'] = None
    intent_path.write_text(json.dumps(intent), encoding='utf-8')
    # The fixture only calls navigation endpoints. Its worker executable is deliberately absent.
    jobs = Jobs(target.parent, target.parent / 'worker-disabled.exe')
    server = BoundedServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    server.RequestHandlerClass = handler(jobs, 'http://127.0.0.1:3015', server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sid, epoch = secrets.token_hex(16), secrets.token_hex(16)

    def request(action, body=None, raw=None, sequence=None):
        headers = {'Origin': 'http://127.0.0.1:3015', 'X-Sphere-Reconstruction': '1', 'X-Job-Key': key}
        if raw is None:
            raw = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        else:
            headers.update({'Content-Type': 'image/jpeg', 'X-Route-Session': sid,
                            'X-Capture-Epoch': epoch, 'X-Frame-Sequence': str(sequence), 'X-Walk-Motion': '0'})
        with urlopen(Request(f'http://127.0.0.1:{server.server_address[1]}/jobs/{target.name}/navigation/{action}',
                             data=raw, headers=headers), timeout=15) as response:
            return json.load(response)

    rows, skipped, opened = [], 0, False
    try:
        start = request('vehicle-start', dict(id=sid, captureEpoch=epoch, width=geometry[0],
            height=geometry[1], sceneConfirmed=True, vehicleCameraAssumptionConfirmed=True,
            cameraFollowsBodyConfirmed=True, hudProfile='black_russia_scooter_v1', maxSpeedKmh=5,
            cameraTracking=True, cameraControl='continuous_drag_v1', clientVersion='vehicle_live_v1',
            startMode=start_mode, speedMode='visual_tempo_live_hud', expectedSource=expected))
        opened = True
        if start['physicalActions'] != 0:
            raise RuntimeError('vehicle_replay_scope')
        wall, first, last = None, None, -1.0
        for row, image in frames:
            seconds = row['relative_ticks_90k'] / 90000
            if seconds > max_seconds:
                break
            if seconds < from_seconds or row['index'] in excluded or seconds - last < .095:
                continue
            if first is None:
                first, wall = seconds, time.perf_counter()
            due = wall + seconds - first
            delay = due - time.perf_counter()
            if delay < -.1:
                skipped += 1
                continue
            if delay > 0:
                time.sleep(delay)
            last = seconds
            presented = time.perf_counter()
            rgb = cv.resize(image.to_ndarray(format='rgb24'), (960, 540), interpolation=cv.INTER_AREA)
            ok, encoded = cv.imencode('.jpg', cv.cvtColor(rgb, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 92])
            if not ok or len(encoded) > 384 * 1024:
                raise ValueError('vehicle_replay_jpeg')
            raw, sequence = encoded.tobytes(), len(rows) + 1
            sent = time.perf_counter()
            result = request('observe-jpeg', raw=raw, sequence=sequence)
            timing = observation_timing(presented, sent, time.perf_counter())
            if result['physicalActions'] != 0 or result['jpegSha256'] != hashlib.sha256(raw).hexdigest():
                raise RuntimeError('vehicle_replay_scope_or_hash')
            rows.append(dict(index=row['index'], seconds=seconds, pose=result['pose'], vehicle=result['vehicle'],
                             speedObservation=result['speedObservation'], method=result['method'], **timing))
    finally:
        try:
            if opened:
                stopped = request('stop', dict(id=sid))
                if stopped['phase'] != 'closed' or stopped['physicalActions'] != 0:
                    raise RuntimeError('vehicle_replay_stop_unconfirmed')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
    if not rows or thread.is_alive():
        raise RuntimeError('vehicle_replay_incomplete')
    return rows, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--diagnostic', nargs=3, type=Path, metavar=('VIDEO', 'INDEX', 'METADATA'))
    source.add_argument('--holdout', type=Path, help='directory of a validated browser-teach capture')
    parser.add_argument('--from-seconds', type=float, default=0, help='first source timestamp to observe')
    parser.add_argument('--max-seconds', type=float, default=15, help='last source timestamp to observe')
    parser.add_argument('--start-mode', choices=('beginning', 'recognized_route'), default='beginning')
    args = parser.parse_args()
    result = run(args.job, args.output, diagnostic=args.diagnostic, holdout=args.holdout,
                 from_seconds=args.from_seconds, max_seconds=args.max_seconds, start_mode=args.start_mode)
    print(json.dumps({key: value for key, value in result.items() if key not in ('samples', 'sourceHashes')}))


if __name__ == '__main__':
    main()
