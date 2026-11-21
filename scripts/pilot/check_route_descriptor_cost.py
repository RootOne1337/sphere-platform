"""Real recorded images, descriptor-stage timing only; no pose admission or input."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid


def run(job, output, *, solver='epnp', threads=(1,2,4)):
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    from dataclasses import replace
    import cv2 as cv
    import numpy as np
    from motor_worker.browser_teach import validate_browser, decoded_browser
    from motor_worker.policy import PolicyFrame
    from motor_worker.route_localization import SparseRoute
    from motor_worker.route_tracking import AnchoredRouteLocalizer
    from scripts.pilot.resource_guard import windows_memory
    root=Path.cwd().resolve();job=Path(job).resolve();output=Path(output).resolve()
    if (not job.is_relative_to(root/'.local-pilot/reconstruction-jobs')
            or not output.is_relative_to(root/'.local-pilot') or output.exists()
            or solver not in {'epnp','ap3p'} or not threads or any(t not in (1,2,4) for t in threads)
            or windows_memory()['availableRamBytes']<4.75*1024**3):
        raise ValueError('descriptor_profile_scope_or_resources')
    active=json.loads((job/'navigation/active.json').read_bytes())['id']
    receipt=json.loads((job/'navigation'/active/'receipt.json').read_bytes())
    route=SparseRoute.load(job/'navigation'/active/'route.json',sha256=receipt['sha256'])
    route=replace(route,profile=replace(route.profile,width=960,height=540,
                  excluded=(*route.profile.excluded,(.33,.45,.67,1.))))
    capture=validate_browser(job/'input');selected=[];last=-5.
    for row,image in decoded_browser(capture):
        seconds=row['relative_ticks_90k']/90000
        if seconds-last<3. or row['index'] in route.source_frame_indices:continue
        rgb=cv.resize(image.to_ndarray(format='rgb24'),(960,540),interpolation=cv.INTER_AREA)
        ok,jpeg=cv.imencode('.jpg',cv.cvtColor(rgb,cv.COLOR_RGB2BGR),[cv.IMWRITE_JPEG_QUALITY,92])
        if not ok or len(jpeg)>384*1024:raise ValueError('descriptor_profile_jpeg')
        selected.append((row['index'],seconds,jpeg.tobytes()));last=seconds
        if len(selected)==16:break
    all_rows=[]
    for native_threads in threads:
        cv.setNumThreads(native_threads)
        for index,seconds,raw in selected:
            epoch,episode,goal=(str(uuid.uuid4()) for _ in range(3))
            tracker=AnchoredRouteLocalizer(route,capture_epoch=epoch,episode_id=episode,
                goal_revision=goal,clock=lambda:100.,recovery_candidate_limit=8)
            stage={};clock=time.perf_counter
            def measured(name, function):
                def call(*args,**kwargs):
                    at=clock()
                    try:return function(*args,**kwargs)
                    finally:stage[name]=stage.get(name,0.)+(clock()-at)*1000
                return call
            for name,method in [('extractMs','_extract'),('coarseMs','_coarse_matches'),('subsetsMs','_solve_subset'),('pnpMs','_verify_correspondences')]:
                setattr(tracker,method,measured(name,getattr(tracker,method)))
            rgb=cv.cvtColor(cv.imdecode(np.frombuffer(raw,np.uint8),cv.IMREAD_COLOR),cv.COLOR_BGR2RGB).tobytes()
            tracker._frame=PolicyFrame(epoch,1,100.,960,540,rgb)
            original=cv.solvePnPRansac
            def proposal(*args,**kwargs):
                kwargs['flags']=cv.SOLVEPNP_AP3P if solver=='ap3p' else cv.SOLVEPNP_EPNP
                return original(*args,**kwargs)
            cv.solvePnPRansac=proposal
            try:
                began=clock();solved=tracker._solve_descriptors();elapsed=(clock()-began)*1000
            finally:cv.solvePnPRansac=original
            all_rows.append(dict(nativeThreads=native_threads,index=index,seconds=seconds,totalMs=elapsed,
                correspondences=0 if solved is None else solved[2],
                center=None if solved is None else solved[0].tolist(),rotation=None if solved is None else solved[1].reshape(-1).tolist(),**stage))
    summary=[]
    for native_threads in threads:
        rows=[r for r in all_rows if r['nativeThreads']==native_threads]
        summary.append(dict(nativeThreads=native_threads,samples=len(rows),
            timings={key:dict(p50=float(np.median([r.get(key,0.) for r in rows])),p95=float(np.percentile([r.get(key,0.) for r in rows],95)))
                for key in ('totalMs','extractMs','coarseMs','subsetsMs','pnpMs')},
            rawPnpSolved=sum(r['correspondences']>=20 for r in rows)))
    result=dict(schema='sphere-descriptor-stage-cost-v1',physicalActions=0,poseAdmissionTest=False,
        sourceManifestSha256=hashlib.sha256((job/'input/manifest.json').read_bytes()).hexdigest(),
        routeSha256=receipt['sha256'],solver=solver,coldMatcherPerQuery=True,candidateLimit=8,summary=summary,rows=all_rows)
    with output.open('x',encoding='utf-8') as file:json.dump(result,file,indent=2)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--solver',choices=('epnp','ap3p'),default='epnp');parser.add_argument('--threads',type=int,nargs='+',choices=(1,2,4),default=(1,2,4))
    args=parser.parse_args();print(json.dumps(run(args.job,args.output,solver=args.solver,threads=args.threads)['summary']))
