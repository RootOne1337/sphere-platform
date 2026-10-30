"""Entire saved video -> bounded production HTTP pose/planner, latest-only.

Held-out source frames, receiver wall clock, binary JPEG, no Android input.
The video does NOT respond to commands: this is not closed-loop navigation.
Only a minimal isolated fixture is created, then discarded with its receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.request import Request,urlopen


def run(source, output):
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np
    from motor_worker.browser_teach import validate_browser,decoded_browser
    from motor_worker.route_localization import SparseRoute
    from scripts.pilot.reconstruction_service import Jobs,BoundedServer,handler
    from scripts.pilot.route_replay_snapshot import snapshot,discard_snapshot
    from scripts.pilot.resource_guard import windows_memory
    from scripts.pilot.check_route_localization_cost import private_bytes

    root=Path.cwd().resolve();source=Path(source).resolve();output=Path(output).resolve()
    if (not source.is_relative_to(root/'.local-pilot/reconstruction-jobs') or not output.is_relative_to(root/'.local-pilot')
            or output.exists() or windows_memory()['availableRamBytes']<4.75*1024**3):
        raise ValueError('full_replay_scope_or_resources')
    nav=json.loads((source/'navigation/active.json').read_bytes())['id']
    receipt=json.loads((source/'navigation'/nav/'receipt.json').read_bytes())
    route=SparseRoute.load(source/'navigation'/nav/'route.json',sha256=receipt['sha256'])
    files=[source/'geometry.json',source/'input/manifest.json',source/'navigation'/nav/'route.json']
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    capture=validate_browser(source/'input');excluded=set(route.source_frame_indices);cv.setNumThreads(4)
    output.mkdir();key=secrets.token_hex(32);identity=secrets.token_hex(16);target=output/'jobs'/identity
    snapshot(source,target,key)
    jobs=Jobs(output/'jobs',root/'.local-pilot/motor-amd-venv/Scripts/python.exe')
    server=BoundedServer(('127.0.0.1',0),BaseHTTPRequestHandler);server.RequestHandlerClass=handler(jobs,'http://127.0.0.1:3015',server.server_address[1])
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    sid,epoch=secrets.token_hex(16),secrets.token_hex(16)

    def request(action, body=None, raw=None, sequence=None):
        headers={'Origin':'http://127.0.0.1:3015','X-Sphere-Reconstruction':'1','X-Job-Key':key}
        if raw is not None:
            headers.update({'Content-Type':'image/jpeg','X-Route-Session':sid,'X-Capture-Epoch':epoch,'X-Frame-Sequence':str(sequence)})
        else:raw=json.dumps(body).encode()
        with urlopen(Request(f'http://127.0.0.1:{server.server_address[1]}/jobs/{identity}/navigation/{action}',data=raw,headers=headers),timeout=10) as response:
            return json.load(response)

    rows=[];skipped=0;last_media=-1.;sequence=0;opened=False;cpu=time.process_time();wall=time.perf_counter();peak_private=private_bytes()
    try:
        request('walk-start',dict(id=sid,captureEpoch=epoch,width=capture.geometry[0],height=capture.geometry[1],sceneConfirmed=True,
            footCameraAssumptionConfirmed=True,startMode='recognized_route',cameraTracking=True,cameraControl='continuous_drag_v1'))
        opened=True;wall=time.perf_counter();first_media=None
        for row,image in decoded_browser(capture):
            seconds=row['relative_ticks_90k']/90000
            if first_media is None:first_media=seconds
            if row['index'] in excluded or seconds-last_media<.095:continue
            due=wall+seconds-first_media;lag=time.perf_counter()-due
            if lag>.1:skipped+=1;continue
            if lag<0:time.sleep(-lag)
            last_media=seconds;sequence+=1
            rgb=cv.resize(image.to_ndarray(format='rgb24'),(960,540),interpolation=cv.INTER_AREA)
            encoded,jpeg=cv.imencode('.jpg',cv.cvtColor(rgb,cv.COLOR_RGB2BGR),[cv.IMWRITE_JPEG_QUALITY,92])
            if not encoded:raise RuntimeError('jpeg')
            raw=jpeg.tobytes();began=time.perf_counter()
            result=request('observe-jpeg',raw=raw,sequence=sequence)
            elapsed=(time.perf_counter()-began)*1000
            if result['jpegSha256']!=hashlib.sha256(raw).hexdigest() or result['physicalActions']!=0:raise RuntimeError('query_scope_or_hash')
            pose,plan=result['pose'],result['walk']
            rows.append(dict(index=row['index'],seconds=seconds,pose=pose['state'],poseReason=pose['reason'],inliers=pose['inliers'],
                segment=pose['segment'],center=pose['center'],rotation=pose['rotation'],poseProgress=pose['progress_units'],
                crossTrackUnits=pose['cross_track_units'],medianErrorPx=pose['median_error_px'],phase=plan['phase'],reason=plan['reason'],stick=plan['stick'],
                effectiveStick=plan['stick'] if elapsed<=250 else [0,0],progress=plan['progressFraction'],targetViewCamera=plan.get('targetViewCamera'),
                computeMs=result['computeMs'],replyMs=elapsed,method=result['method']))
            peak_private=max(peak_private,private_bytes())
            if sequence%100==0:print(json.dumps(dict(observations=sequence,sourceSeconds=seconds,phase=plan['phase'],pose=pose['state'])),flush=True)
    finally:
        if opened:request('stop',dict(id=sid))
        server.shutdown();server.server_close();thread.join(3)
        if not thread.is_alive():discard_snapshot(target,output/'fixture-receipt.json')
    from collections import Counter
    result=dict(schema='sphere-route-entire-video-http-check-v1',physicalActions=0,independentGameplay=False,closedLoop=False,
        syntheticSourceClock=False,latestOnly=True,referenceFramesExcluded=True,sourceHashes=hashes,
        sourceUnchanged=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==sha for p,sha in hashes.items()),
        observations=len(rows),skippedLate=skipped,firstSeconds=rows[0]['seconds'],lastSeconds=rows[-1]['seconds'],
        counts=dict(Counter(r['pose'] for r in rows)),planReasons=dict(Counter(r['reason'] for r in rows)),
        cpuCoreSeconds=time.process_time()-cpu,wallSeconds=time.perf_counter()-wall,peakSampledPrivateBytes=peak_private,
        replyMs=dict(p50=float(np.median([r['replyMs'] for r in rows])),p95=float(np.percentile([r['replyMs'] for r in rows],95)),maximum=max(r['replyMs'] for r in rows)),
        expiredReplies=sum(r['replyMs']>250 for r in rows),samples=rows)
    (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=run(args.job,args.output);print(json.dumps({k:v for k,v in r.items() if k not in {'samples','sourceHashes'}}))
