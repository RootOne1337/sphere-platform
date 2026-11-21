"""Bounded real-RGB CPU/memory diagnostic; synthetic source clock, no Android.

Reports CPU core-seconds, not CPU percentage inferred from wall time. Neither
recorded input nor query time/identity is supplied to localization or planning.
This is a single-process cost estimate, NOT a multi-emulator capacity test.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def private_bytes():
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
            'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    data=Counters();data.cb=ctypes.sizeof(data)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(data),data.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(data.PrivateUsage)


def run(job, output, *, count=64):
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    cpu_runtime=initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np
    from motor_worker.browser_teach import decoded_browser,validate_browser
    from motor_worker.policy import PolicyFrame
    from motor_worker.route_localization import SparseRoute
    from motor_worker.route_tracking import AnchoredRouteLocalizer
    from motor_worker.walk_route import WalkRouteFollower
    from scripts.pilot.resource_guard import windows_memory
    root=Path.cwd().resolve();job=Path(job).resolve();output=Path(output).resolve()
    if (not job.is_relative_to(root/'.local-pilot/reconstruction-jobs')
            or not output.is_relative_to(root/'.local-pilot') or output.exists() or not 16<=count<=96):
        raise ValueError('cost_diagnostic_scope')
    # This is the same bounded CPU map/query path, not feature extraction for
    # a reconstruction. Do not reintroduce the old 6 GiB live-start threshold.
    if windows_memory()['availableRamBytes']<4.75*1024**3:
        raise RuntimeError('cost_diagnostic_memory_guard')
    active=json.loads((job/'navigation/active.json').read_bytes())['id']
    receipt=json.loads((job/'navigation'/active/'receipt.json').read_bytes())
    paths=[job/'geometry.json',job/'input/manifest.json',job/'navigation'/active/'route.json']
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    base=private_bytes()
    route=SparseRoute.load(paths[-1],sha256=receipt['sha256'])
    route=replace(route,profile=replace(route.profile,width=960,height=540,
                  excluded=(*route.profile.excluded,(.33,.45,.67,1.))))
    map_bytes=private_bytes();capture=validate_browser(job/'input');queries=[];last=-1.
    for row,image in decoded_browser(capture):
        seconds=row['relative_ticks_90k']/90000
        if seconds<4 or seconds-last<.095 or row['index'] in route.source_frame_indices:
            continue
        rgb=cv.resize(image.to_ndarray(format='rgb24'),(960,540),interpolation=cv.INTER_AREA)
        ok,jpeg=cv.imencode('.jpg',cv.cvtColor(rgb,cv.COLOR_RGB2BGR),[cv.IMWRITE_JPEG_QUALITY,92])
        if not ok:raise RuntimeError('query_jpeg')
        queries.append((row['index'],seconds,jpeg.tobytes()));last=seconds
        if len(queries)==count:break
    if len(queries)!=count:raise ValueError('query_coverage')
    cases=[]
    for threads in (1,4):
        cv.setNumThreads(threads);cv.setRNGSeed(7);now=100.
        epoch,episode,goal=(str(uuid.uuid4()) for _ in range(3))
        tracker=AnchoredRouteLocalizer(route,capture_epoch=epoch,episode_id=episode,
                    goal_revision=goal,clock=lambda:now)
        follower=WalkRouteFollower(route,clock=lambda:now,start_mode='recognized_route')
        rows=[];before_tracker=private_bytes()
        for sequence,(index,seconds,jpeg) in enumerate(queries,1):
            now=100.+seconds-queries[0][1]
            cpu,wall=time.process_time(),time.perf_counter()
            bgr=cv.imdecode(np.frombuffer(jpeg,np.uint8),cv.IMREAD_COLOR)
            rgb=cv.cvtColor(bgr,cv.COLOR_BGR2RGB).tobytes()
            frame=PolicyFrame(epoch,sequence,now,960,540,rgb)
            pose=tracker.observe(frame,episode_id=episode,goal_revision=goal,scene='active')
            plan=follower.observe(pose)
            rows.append(dict(index=index,sourceSeconds=seconds,method=tracker.last_diagnostic['method'],
                pose=pose.state,plan=plan['phase'],cpuMs=(time.process_time()-cpu)*1000,
                wallMs=(time.perf_counter()-wall)*1000,inliers=pose.inliers))
        core_seconds=sum(row['cpuMs'] for row in rows)/1000
        cadence_seconds=(queries[-1][1]-queries[0][1])*len(queries)/(len(queries)-1)
        cases.append(dict(nativeThreads=threads,rows=rows,cpuCoreSeconds=core_seconds,
            sourceCadenceSeconds=cadence_seconds,estimatedCoresPerContinuouslyActiveWindow=core_seconds/cadence_seconds,
            arithmetic100WindowsCores=100*core_seconds/cadence_seconds,
            privateBytesBeforeTracker=before_tracker,privateBytesAfterQueries=private_bytes()))
    unchanged=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    result=dict(schema='sphere-route-localization-cost-v1',physicalActions=0,
        cpuRuntime=cpu_runtime,
        sourceHashes=hashes,sourceUnchanged=unchanged,syntheticSourceClock=True,
        queryFramesHeldOut=True,independentGameplay=False,multiWindowLoadTest=False,
        excludes=['video_decode_in_browser','stream_encode','HTTP','browser_UI','Android','GPU_reconstruction'],
        privateBytesBeforeMap=base,privateBytesAfterMap=map_bytes,cases=cases)
    with output.open('x',encoding='utf-8') as file:json.dump(result,file,indent=2)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--count',type=int,default=64);args=parser.parse_args()
    result=run(args.job,args.output,count=args.count)
    print(json.dumps({k:v for k,v in result.items() if k not in {'cases','sourceHashes'}}))
    for case in result['cases']:
        print(json.dumps({k:v for k,v in case.items() if k!='rows'}))
