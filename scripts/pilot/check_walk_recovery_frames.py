"""Bounded descriptor cost on exact retained live JPEGs; no input or source writes."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import zipfile
import uuid


def run(job,archive,output):
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np
    from motor_worker.route_localization import SparseRoute,RouteLocalizer,extract_features
    from motor_worker.route_tracking import AnchoredRouteLocalizer
    from motor_worker.policy import PolicyFrame
    from scripts.pilot.resource_guard import windows_memory
    root=Path.cwd().resolve();job=job.resolve();output=output.resolve()
    if not job.is_relative_to(root/'.local-pilot/reconstruction-jobs')or not output.is_relative_to(root/'.local-pilot')or output.exists():raise ValueError('diagnostic_scope')
    if windows_memory()['availableRamBytes']<4.75*2**30:raise RuntimeError('resource_guard')
    active=json.loads((job/'navigation/active.json').read_bytes())['id'];folder=job/'navigation'/active
    receipt=json.loads((folder/'receipt.json').read_bytes());route=SparseRoute.load(folder/'route.json',sha256=receipt['sha256'])
    route=replace(route,profile=replace(route.profile,width=960,height=540,excluded=(*route.profile.excluded,(.33,.45,.67,1.))))
    queries=[]
    with zipfile.ZipFile(archive)as z:
        if sum(e.file_size for e in z.infolist())>2*1024**2 or len(z.infolist())>13:raise ValueError('archive_quota')
        meta=json.loads(z.read('metadata.json'))
        if meta['binding']['geometrySha256']!=hashlib.sha256((job/'geometry.json').read_bytes()).hexdigest():raise ValueError('map_binding')
        # Last four exact images span the failure and reacquisition. Prior 33
        # comes from the last qualified image BEFORE this subset, not its time.
        prior=next(r['segment']for r in reversed(meta['frames'][:-4])if r['poseState']=='localized')
        for row in meta['frames'][-4:]:
            raw=z.read(f"frame-{row['sequence']:06d}.jpg")
            if hashlib.sha256(raw).hexdigest()!=row['jpegSha256']:raise ValueError('frame_hash')
            image=cv.imdecode(np.frombuffer(raw,np.uint8),cv.IMREAD_COLOR)
            if image.shape!=(540,960,3):raise ValueError('frame_geometry')
            queries.append((row,cv.cvtColor(image,cv.COLOR_BGR2RGB).tobytes()))
    rows=[];began=time.monotonic()
    for threads in (1,2,4):
        cv.setNumThreads(threads)
        for row,rgb in queries:
            for limit in (8,3):
                if time.monotonic()-began>120:raise RuntimeError('diagnostic_timeout')
                now=100.;epoch,episode,goal=(str(uuid.uuid4())for _ in range(3))
                tracker=AnchoredRouteLocalizer(route,capture_epoch=epoch,episode_id=episode,goal_revision=goal,clock=lambda:now,candidate_limit=limit)
                tracker._recovery_hint=(prior,now-.2);tracker.last_received=now
                frame=PolicyFrame(epoch,1,now,960,540,rgb);start=time.perf_counter()
                pixels,descriptors=extract_features(frame,tracker.mask);extracted=time.perf_counter();cv.setRNGSeed(7)
                solution=RouteLocalizer._solve(tracker,pixels,descriptors);ended=time.perf_counter()
                rows.append(dict(threads=threads,candidates=limit,sequence=row['sequence'],recordedState=row['poseState'],
                    features=len(pixels),extractMs=(extracted-start)*1000,solveMs=(ended-extracted)*1000,totalMs=(ended-start)*1000,
                    inliers=None if solution is None else solution[2],center=None if solution is None else solution[0].tolist(),rotation=None if solution is None else solution[1].tolist()))
    output.mkdir();result=dict(schema='sphere-exact-live-recovery-cost-v1',physicalActions=0,realQueryImages=True,offline=True,
        absoluteAccuracyVerified=False,priorReference=prior,priorFromPreviousQualifiedImage=True,
        archiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),routeSha256=receipt['sha256'],cases=rows)
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for threads in (1,2,4):
        for candidates in (8,3):
            group=[r for r in rows if r['threads']==threads and r['candidates']==candidates]
            print(json.dumps(dict(threads=threads,candidates=candidates,maximumMs=max(r['totalMs']for r in group),meanMs=sum(r['totalMs']for r in group)/len(group),inliers=[r['inliers']for r in group])))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();run(args.job,args.archive,args.output)
