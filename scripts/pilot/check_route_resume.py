"""Real saved RGB -> HTTP localization -> midroute plan. No native input client."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.pilot.reconstruction_service import ROOT, BoundedServer, Jobs, handler
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_replay_snapshot import snapshot, discard_snapshot


def run(source_job, output, *, source_seconds=10., camera_tracking=False):
    import cv2 as cv
    from motor_worker.browser_teach import decoded_browser, validate_browser
    from motor_worker.route_localization import SparseRoute

    source_job, output = Path(source_job).resolve(), Path(output).resolve()
    allowed = (ROOT/'.local-pilot').resolve()
    if (output.exists() or not output.is_relative_to(allowed) or output == allowed
            or source_job.is_relative_to(output) or not 5 <= source_seconds <= 540):
        raise ValueError('resume_check_scope')
    if evaluate(collect(ROOT), min_ram_gib=6, min_disk_gib=1):
        raise RuntimeError('resource_guard')
    active = json.loads((source_job/'navigation/active.json').read_bytes())['id']
    receipt = json.loads((source_job/'navigation'/active/'receipt.json').read_bytes())
    route = SparseRoute.load(source_job/'navigation'/active/'route.json', sha256=receipt['sha256'])
    capture = validate_browser(source_job/'input')
    excluded = set(route.source_frame_indices)
    paths = [source_job/'geometry.json', source_job/'input/manifest.json',
             source_job/'navigation'/active/'route.json']
    original = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frames = []
    cv.setNumThreads(4)
    for row, image in decoded_browser(capture):
        seconds = row['relative_ticks_90k']/90000
        if seconds < source_seconds or row['index'] in excluded:
            continue
        if frames and seconds-frames[-1]['sourceSeconds'] < .18:
            continue
        rgb = cv.resize(image.to_ndarray(format='rgb24'), (960, 540), interpolation=cv.INTER_AREA)
        ok, jpeg = cv.imencode('.jpg', cv.cvtColor(rgb, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 92])
        if not ok or len(jpeg) > 384*1024:
            raise RuntimeError('query_jpeg_quota')
        frames.append(dict(index=row['index'], sourceSeconds=seconds, jpeg=base64.b64encode(jpeg).decode()))
        if len(frames) == 10:
            break
    if len(frames) != 10:
        raise ValueError('resume_query_coverage')
    output.mkdir()
    (output/'intent.json').write_text(json.dumps(dict(scope='OFFLINE_HTTP_PLAN_ONLY', physicalActions=0,
        sourceHashes=original, excludedReferenceFrames=True, queryIndices=[f['index'] for f in frames])))
    identity, key = secrets.token_hex(32)[:32], secrets.token_hex(32)
    target = output/'jobs'/identity
    fixture = snapshot(source_job, target, key)
    jobs = Jobs(output/'jobs', ROOT/'.local-pilot/motor-amd-venv/Scripts/python.exe')
    server = BoundedServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.RequestHandlerClass = handler(jobs, 'http://127.0.0.1:3015', port)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()

    def request(action, body):
        with urlopen(Request(f'http://127.0.0.1:{port}/jobs/{identity}/navigation/{action}',
                method='POST', data=json.dumps(body).encode(), headers={'Origin':'http://127.0.0.1:3015',
                    'X-Sphere-Reconstruction':'1', 'X-Job-Key':key}), timeout=10) as response:
            return json.load(response)

    cases = []
    try:
        for mode in ('beginning', 'recognized_route'):
            sid, epoch = secrets.token_hex(16), secrets.token_hex(16)
            opened = request('walk-start', dict(id=sid, captureEpoch=epoch, width=capture.geometry[0],
                height=capture.geometry[1], sceneConfirmed=True, footCameraAssumptionConfirmed=True,
                startMode=mode,cameraTracking=camera_tracking,**({'cameraControl':'continuous_drag_v1'} if camera_tracking else {})))
            if opened['startMode'] != mode:
                raise RuntimeError('start_mode_not_acknowledged')
            if opened.get('cameraTracking') is not camera_tracking:
                raise RuntimeError('camera_mode_not_acknowledged')
            if camera_tracking and opened.get('cameraControl')!='continuous_drag_v1':
                raise RuntimeError('camera_control_not_acknowledged')
            rows = []
            try:
                for i, frame in enumerate(frames):
                    began = time.perf_counter()
                    value = request('observe', dict(id=sid, captureEpoch=epoch, sequence=i+1, jpeg=frame['jpeg']))
                    age = (time.perf_counter()-began)*1000
                    if value['physicalActions'] != 0 or value['executionQualified'] is not False:
                        raise RuntimeError('plan_scope_changed')
                    pose, plan = value['pose'], value['walk']
                    rows.append(dict(queryIndex=frame['index'], sourceSeconds=frame['sourceSeconds'],
                        pose=pose['state'], inliers=pose['inliers'], segment=pose['segment'],
                        phase=plan['phase'], reason=plan['reason'], progress=plan['progressFraction'],
                        planStick=plan['stick'], effectiveStick=plan['stick'] if age <= 250 else [0, 0],
                        targetCamera=plan.get('targetCamera'),referenceTicks90k=value.get('referenceTicks90k'),
                        replyAgeMs=age, computeMs=value['computeMs']))
                    time.sleep(max(0, .18-(time.perf_counter()-began)))
            finally:
                request('stop', dict(id=sid))
            cases.append(dict(startMode=mode, samples=rows))
    finally:
        server.shutdown();server.server_close();thread.join(3)
        if not thread.is_alive():discard_snapshot(target,output/'fixture-receipt.json')
    unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p, sha in original.items())
    result = dict(schema='sphere-offline-route-resume-v1', physicalActions=0, originalFilesUnchanged=unchanged,
        heldOutSourceFrames=True, independentGameplay=False, feedbackLoop=False,cameraTracking=camera_tracking,
        fixtureBytes=fixture['copiedBytes'],cases=cases)
    (output/'result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-seconds', type=float, default=10.)
    parser.add_argument('--camera-tracking',action='store_true')
    args = parser.parse_args()
    report = run(args.job, args.output, source_seconds=args.source_seconds,camera_tracking=args.camera_tracking)
    print(json.dumps({k:v for k,v in report.items() if k != 'cases'}))
    for case in report['cases']:
        print(json.dumps(dict(startMode=case['startMode'], phases=[s['phase'] for s in case['samples']],
            localized=sum(s['pose']=='localized' for s in case['samples']),
            effectiveMovement=sum(any(s['effectiveStick']) for s in case['samples']))))
