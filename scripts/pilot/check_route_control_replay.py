"""Recorded JPEG -> real HTTP pose/planner path, with no native-input client.

This is an open-loop replay: commands cannot change the recorded future. It
tests protocol, localization, timing and neutral stops, not successful driving.
Source indices/times are used only by the playback scheduler/report, never sent
to localization. Reference source frames are excluded from positive queries.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request,urlopen

from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruction_service import BoundedServer,Jobs,ROOT,handler
from scripts.pilot.resource_guard import collect,evaluate
from scripts.pilot.route_replay_snapshot import snapshot, discard_snapshot


def digest(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def run(source_job,query_input,output,*,cases=('baseline','freeze','gap','late_reply'),seconds=55,fault_after=2):
    import cv2 as cv
    import numpy as np
    from motor_worker.browser_teach import decoded_browser,validate_browser
    from motor_worker.route_localization import SparseRoute

    source_job,query_input,output=(Path(p).resolve() for p in (source_job,query_input,output))
    pilot=(ROOT/'.local-pilot').resolve()
    if (output.exists() or output==pilot or not output.is_relative_to(pilot)
            or source_job.is_relative_to(output) or query_input.is_relative_to(output)
            or not cases or len(set(cases))!=len(cases)
            or any(case not in {'baseline','freeze','gap','late_reply','jpeg60','blackout'} for case in cases)
            or type(seconds) not in (int,float) or not 5<=seconds<=55
            or type(fault_after) not in (int,float) or not .5<=fault_after<=10):
        raise ValueError('control_replay_scope_or_quota')
    if evaluate(collect(ROOT),min_ram_gib=6,min_disk_gib=1):raise RuntimeError('resource_guard')
    capture=validate_browser(query_input);query_sha=digest(query_input/'manifest.json')
    active=json.loads((source_job/'navigation/active.json').read_bytes())['id']
    nav=source_job/'navigation'/active;receipt=json.loads((nav/'receipt.json').read_bytes())
    route=SparseRoute.load(nav/'route.json',sha256=receipt['sha256'])
    if json.loads((nav/'state.json').read_bytes())['phase']!='ready':raise ValueError('control_replay_requires_ready_map')
    excluded=set(route.source_frame_indices) if query_sha==route.source_capture_sha256 else set()
    originals={str(p.relative_to(source_job)):digest(p) for p in
        [source_job/'geometry.json',*source_job.glob('input/*'),nav/'route.json',nav/'receipt.json'] if p.is_file()}
    recipe={name:digest(ROOT/name) for name in ('scripts/pilot/check_route_control_replay.py','scripts/pilot/route_workspace.py',
        'scripts/pilot/reconstruction_service.py','motor_worker/route_localization.py','motor_worker/route_tracking.py','motor_worker/walk_route.py')}
    output.mkdir();write_json(output/'intent.json',dict(scope='RECORDED_HTTP_PLAN_ONLY',queryManifestSha=query_sha,
        sourceHashes=originals,cases=list(cases),recipeSourceHashes=recipe,faultAfterSeconds=fault_after,physicalActions=0))
    # Copy only the bounded files read by localization; a fresh capability
    # exists only in memory. Video, SfM databases and old models stay at source.
    identity,key=secrets.token_hex(16),secrets.token_hex(32)
    job=output/'jobs'/identity;snapshot(source_job,job,key)
    cv.setNumThreads(2);frames=[];last=-1.;checked=time.monotonic()
    for row,image in decoded_browser(capture):
        media=row['relative_ticks_90k']/90000
        if media>seconds:break
        if row['index'] in excluded or media-last<.2:continue
        if time.monotonic()-checked>3:
            if evaluate(collect(ROOT),min_ram_gib=6,min_disk_gib=1):raise RuntimeError('resource_guard')
            checked=time.monotonic()
        rgb=cv.resize(image.to_ndarray(format='rgb24'),(960,540),interpolation=cv.INTER_AREA)
        encoded={}
        for quality in (92,60):
            ok,raw=cv.imencode('.jpg',cv.cvtColor(rgb,cv.COLOR_RGB2BGR),[cv.IMWRITE_JPEG_QUALITY,quality])
            if not ok or len(raw)>384*1024:raise ValueError('control_replay_jpeg_quota')
            encoded[quality]=raw.tobytes()
        frames.append(dict(index=row['index'],media=media,jpegs=encoded));last=media
        if len(frames)>280:raise ValueError('control_replay_frame_quota')
    if len(frames)<10:raise ValueError('control_replay_insufficient_queries')
    jobs=Jobs(output/'jobs',ROOT/'.local-pilot/motor-amd-venv/Scripts/python.exe')
    server=BoundedServer(('127.0.0.1',0),BaseHTTPRequestHandler);port=server.server_address[1]
    server.RequestHandlerClass=handler(jobs,'http://127.0.0.1:3015',port)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();reports=[]

    def request(action,body):
        raw=json.dumps(body).encode()
        with urlopen(Request(f'http://127.0.0.1:{port}/jobs/{identity}/navigation/replay-{action}',
            data=raw,method='POST',headers={'Origin':'http://127.0.0.1:3015','X-Sphere-Reconstruction':'1',
                'X-Job-Key':key,'Content-Type':'application/json'}),timeout=10) as response:
            return json.load(response)
    try:
        for case in cases:
            session,epoch=secrets.token_hex(16),secrets.token_hex(16)
            request('start',dict(id=session,captureEpoch=epoch,width=capture.geometry[0],height=capture.geometry[1]))
            began=time.perf_counter();rows=[];at=0;sequence=0;fault=None;frozen=None;browser_stopped=False
            journal=(output/f'{case}.samples.jsonl').open('x',encoding='utf-8')
            try:
                while at<len(frames):
                    elapsed=time.perf_counter()-began
                    while at+1<len(frames) and frames[at+1]['media']<=elapsed:at+=1
                    frame=frames[at]
                    if case not in {'baseline','jpeg60'} and frame['media']>14:break
                    wait=frame['media']-(time.perf_counter()-began)
                    if wait>0:time.sleep(min(wait,.25));continue
                    raw=frame['jpegs'][60 if case=='jpeg60' else 92]
                    if frame['media']>=fault_after and case=='gap' and fault is None:
                        fault='observation_gap_700ms';time.sleep(.7);continue
                    if fault_after<=frame['media']<fault_after+1 and case=='freeze':
                        if frozen is None:frozen=raw
                        raw=frozen;fault='repeated_rgb_1s'
                    if fault_after<=frame['media']<fault_after+1 and case=='blackout':
                        _,blank=cv.imencode('.jpg',np.zeros((540,960,3),np.uint8));raw=blank.tobytes();fault='blackout_1s'
                    sequence+=1;captured=time.perf_counter()
                    response=request('observe',dict(id=session,captureEpoch=epoch,sequence=sequence,
                        jpeg=base64.b64encode(raw).decode()))
                    if case=='late_reply' and frame['media']>=fault_after and fault is None:
                        time.sleep(.3);fault='response_delivery_delayed_300ms'
                    age=(time.perf_counter()-captured)*1000;pose=response['pose'];plan=response['walk']
                    if response.get('replayOnly') is not True or response['physicalActions']!=0:
                        raise RuntimeError('control_replay_reply_scope')
                    if age>250:browser_stopped=True
                    effective=[0.,0.] if browser_stopped else plan['stick']
                    rows.append(dict(sourceIndex=frame['index'],mediaSeconds=frame['media'],sequence=sequence,
                        pose=pose,plan=plan,replyMs=age,computeMs=response['computeMs'],
                        effectiveStick=effective,browserStopped=browser_stopped,
                        jpegSha256=response['jpegSha256'],method=response['method']))
                    journal.write(json.dumps(rows[-1])+'\n');journal.flush()
                    if len(rows) in {8,35,65}:
                        proof=cv.imdecode(np.frombuffer(raw,np.uint8),cv.IMREAD_COLOR)
                        line=pose['polyline_px']
                        if pose['state']=='localized' and len(line)>=2:cv.polylines(proof,[np.array(line,dtype='int32')],False,(210,230,60),2,cv.LINE_AA)
                        cv.rectangle(proof,(0,0),(959,55),(24,17,10),-1)
                        cv.putText(proof,f"REPLAY ONLY / {case} / {frame['media']:.2f}s / {plan['phase']}",(12,22),cv.FONT_HERSHEY_SIMPLEX,.55,(240,240,240),1,cv.LINE_AA)
                        cv.putText(proof,f"stick {effective[0]:+.2f}, {effective[1]:+.2f} / inliers {pose['inliers']} / {age:.0f}ms",(12,44),cv.FONT_HERSHEY_SIMPLEX,.5,(150,230,230),1,cv.LINE_AA)
                        cv.imwrite(str(output/f'{case}-{len(rows)}.jpg'),proof)
                    at+=1
            finally:
                journal.close();request('stop',dict(id=session))
            first_stop=next((r for r in rows if r['plan']['phase']=='stopped'),None)
            report=dict(case=case,samples=rows,states=dict(Counter(r['pose']['state'] for r in rows)),
                plans=dict(Counter(r['plan']['phase'] for r in rows)),fault=fault,
                firstStop=None if first_stop is None else dict(seconds=first_stop['mediaSeconds'],reason=first_stop['plan']['reason']),
                firstFollowingSeconds=next((r['mediaSeconds'] for r in rows if r['plan']['phase']=='following'),None),
                browserExpiredReplies=sum(r['replyMs']>250 for r in rows),
                effectiveMovingSamples=sum(bool(np.linalg.norm(r['effectiveStick'])>0) for r in rows))
            write_json(output/f'{case}.json',report);reports.append({k:v for k,v in report.items() if k!='samples'})
            print(json.dumps(reports[-1]),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join(5)
        if not thread.is_alive():discard_snapshot(job,output/'fixture-receipt.json')
    if (any(digest(source_job/name)!=sha for name,sha in originals.items())
            or any(digest(ROOT/name)!=sha for name,sha in recipe.items())):raise RuntimeError('control_replay_source_changed')
    result=dict(schema='sphere-recorded-control-replay-v1',cases=reports,physicalActions=0,sourceUnchanged=True,
        independentPositiveCapture=False,closedLoop=False,arrivalProven=False,referenceSourceFramesExcluded=len(excluded),
        routeSha256=receipt['sha256'],queryManifestSha256=query_sha,queryTimesSentToLocalizer=False,recipeSourceHashes=recipe,
        afterStop='diagnostic_localization_continues_planner_remains_terminal',nativeInputClientPresent=False)
    write_json(output/'result.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('source-job','query-input','output'):parser.add_argument('--'+field,required=True,type=Path)
    parser.add_argument('--cases',nargs='+',default=['baseline','freeze','gap','late_reply'])
    parser.add_argument('--seconds',type=float,default=55)
    parser.add_argument('--fault-after',type=float,default=2)
    args=parser.parse_args();run(args.source_job,args.query_input,args.output,cases=tuple(args.cases),seconds=args.seconds,fault_after=args.fault_after)


if __name__=='__main__':main()
