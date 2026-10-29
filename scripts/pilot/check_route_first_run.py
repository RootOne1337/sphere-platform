"""Exercise the web's first-run HTTP contract on an isolated local job store.

The client creates/uploads/starts once, then only reads state. The production
monitor must prepare navigation itself. No manual model selection, adoption,
pose correction, Android connection or input command is available here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruction_service import BoundedServer, Jobs, LIMITS, ROOT, TERMINAL, handler
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_motion_audit import audit
from scripts.pilot.sparse_scene_receipt import verify_sparse_receipt

FILES=('manifest.json','frames.jsonl','inputs.jsonl','video.h264','COMPLETE')
RECIPE=('scripts/pilot/check_route_first_run.py','scripts/pilot/reconstruction_service.py','scripts/pilot/reconstruct_route.py',
        'scripts/pilot/route_workspace.py','scripts/pilot/prepare_route_workspace.py',
        'scripts/pilot/route_video_tracks.py','scripts/pilot/route_motion_sampling.py',
        'scripts/pilot/video_observations.py','scripts/pilot/camera_pixel_conventions.py',
        'scripts/pilot/export_route_localization.py','scripts/pilot/route_landmark_builder.py',
        'motor_worker/browser_teach.py','motor_worker/route_localization.py')


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def stop_unfinished(jobs, job):
    """Do not erase a terminal rejection by cancelling an already finished task."""
    if not job.exists():return
    phase=json.loads((job/'state.json').read_bytes())['phase']
    if phase not in TERMINAL:(job/'CANCEL').touch(exist_ok=True)
    navigation=jobs.navigation.current(job)
    if navigation is not None and jobs.navigation.preparing(job):
        (navigation/'CANCEL').touch(exist_ok=True)


def run(source,output,worker,*,timeout=900):
    source,output,worker=map(lambda p:Path(p).resolve(),(source,output,worker))
    pilot=(ROOT/'.local-pilot').resolve()
    if (output==pilot or not output.is_relative_to(pilot) or output.exists()
            or source.is_relative_to(output) or not worker.is_file() or not worker.is_relative_to(ROOT)
            or type(timeout) is not int or not 60<=timeout<=900):
        raise ValueError('first_run_exclusive_local_scope')
    if any(not (source/name).is_file() or (source/name).is_symlink()
           or not 0<(source/name).stat().st_size<=LIMITS[name] for name in FILES):
        raise ValueError('first_run_source_files')
    manifest=json.loads((source/'manifest.json').read_bytes())
    # Match TeachingReconstruction's default for this saved capture, rather
    # than tuning masks after seeing the result.
    mask='avatar' if manifest.get('config',{}).get('hud_hidden_declared') is True else 'game'
    if evaluate(collect(ROOT)):
        raise RuntimeError('resource_guard')
    before={name:digest(source/name) for name in FILES}
    recipe={name:digest(ROOT/name) for name in RECIPE}
    output.mkdir()
    write_json(output/'intent.json',dict(scope='ISOLATED_WEB_HTTP_FIRST_RUN',sourceHashes=before,
               recipeSourceHashes=recipe,worker=str(worker.relative_to(ROOT)),mask=mask,physicalActions=0))
    jobs=Jobs(output/'jobs',worker)
    server=BoundedServer(('127.0.0.1',0),BaseHTTPRequestHandler)
    port=server.server_address[1]
    server.RequestHandlerClass=handler(jobs,'http://127.0.0.1:3015',port)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    identity=secrets.token_hex(16);key=secrets.token_hex(32);job=jobs.path(identity)
    operations=[];phases=[];started=time.monotonic();current=None
    result=dict(outcome='unknown',physicalActions=0,sourceHashes=before,recipeSourceHashes=recipe,mask=mask)

    def request(method,path,body=None,*,authenticated=True,headers=None,raw=False):
        fields={'X-Sphere-Reconstruction':'1','Origin':'http://127.0.0.1:3015',**(headers or {})}
        if authenticated:fields['X-Job-Key']=key
        if isinstance(body,dict):
            body=json.dumps(body).encode();fields['Content-Type']='application/json'
        response=urlopen(Request(f'http://127.0.0.1:{port}'+path,data=body,headers=fields,method=method),timeout=20)
        operations.append(dict(method=method,path=path))
        content=response.read(16*1024**2)
        return content if raw else json.loads(content)

    def read_status():
        # The web retries reads after a transient file-sharing failure too.
        # No create/upload/start/prepare request is ever repeated here.
        for attempt in range(3):
            try:return request('GET',f'/jobs/{identity}')
            except HTTPError as error:
                if error.code!=503 or attempt==2:raise
                time.sleep(.1*(attempt+1))

    try:
        request('POST','/jobs',dict(id=identity,key=key,mask=mask,steps=30000,prepare_route=True,route_only=True),authenticated=False)
        try:
            request('GET',f'/jobs/{identity}',authenticated=False)
            raise RuntimeError('first_run_missing_capability_not_denied')
        except HTTPError as error:
            if error.code!=403:raise
        offsets=request('GET',f'/jobs/{identity}/offsets')
        if any(offsets[name]!=0 for name in FILES):raise RuntimeError('first_run_not_fresh')
        for name in FILES:
            offset=0
            with (source/name).open('rb') as data:
                while chunk:=data.read(1048576):
                    reply=request('PUT',f'/jobs/{identity}/input/{name}',chunk,
                        headers={'Content-Type':'application/octet-stream','X-Upload-Offset':str(offset)})
                    offset+=len(chunk)
                    if reply.get('offset')!=offset:raise RuntimeError('first_run_upload_not_confirmed')
        # Exactly the same only start command issued by TeachingReconstruction.
        request('POST',f'/jobs/{identity}/start',{})
        while True:
            current=read_status()
            phase=(current['phase'],current.get('navigation',{}).get('phase'))
            if not phases or phases[-1]['state']!=list(phase):
                phases.append(dict(seconds=round(time.monotonic()-started,3),state=list(phase)))
                print(json.dumps(dict(seconds=phases[-1]['seconds'],state=phase)),flush=True)
            if current.get('navigation',{}).get('phase')=='ready':break
            if (current['phase'] in {'failed','cancelled','quality_rejected','review_required'}
                    or current.get('navigation',{}).get('phase') in {'failed','rejected','cancelled'}):
                raise RuntimeError('first_run_not_qualified')
            if time.monotonic()-started>timeout:raise RuntimeError('first_run_deadline')
            time.sleep(2)
        verify_sparse_receipt(job)
        geometry_raw=request('GET',f'/jobs/{identity}/geometry',raw=True)
        geometry=json.loads(geometry_raw);motion=audit(geometry)
        quality=current['quality'];summary=current['navigation']['summary']
        navigation=jobs.navigation.current(job)
        receipt=json.loads((navigation/'receipt.json').read_bytes())
        if (quality['registered']!=quality['selected'] or motion['rapid_reversals'] or motion['speed_outliers']
                or geometry['source_manifest_sha256']!=before['manifest.json']
                or receipt['geometry_sha256']!=hashlib.sha256(geometry_raw).hexdigest()
                or any(digest(job/'input'/name)!=before[name] or digest(source/name)!=before[name] for name in FILES)
                or {name:digest(ROOT/name) for name in RECIPE}!=recipe):
            raise RuntimeError('first_run_acceptance_mismatch')
        expected=hashlib.sha256((identity+':initial-route').encode()).hexdigest()[:32]
        if (navigation.name!=expected or len(list((job/'navigation').glob('*/intent.json')))!=1
                or [op['path'] for op in operations if op['method']=='POST']!=['/jobs',f'/jobs/{identity}/start']):
            raise RuntimeError('first_run_manual_or_repeated_stage')
        result.update(outcome='verified',job=identity,seconds=time.monotonic()-started,
            quality=quality,navigation=summary,navigationPhase='ready',phases=phases,
            sourceHashes=before,recipeSourceHashes=recipe,sourceUnchanged=True,
            clientCreateRequests=1,clientStartRequests=1,clientPrepareRequests=0,
            navigationAttempts=1,manualModelSelection=False,manualAdoption=False,
            sourcePoseEdits=False,executionQualified=False,freshBrowserVisualAcceptance=False,
            automaticMethod=json.loads((job/'prepared/features.json').read_bytes())['method'],mask=mask)
    except Exception as error:
        result.update(outcome='not_confirmed',errorType=type(error).__name__,phases=phases)
        if current is not None:
            result['lastObservedState']=dict(phase=current['phase'],error=current.get('error'),
                navigation={name:current.get('navigation',{}).get(name) for name in ('phase','error')})
        # No mutation is retried on uncertainty. Stop only this isolated job's
        # known workers through their existing cooperative cancellation files.
        stop_unfinished(jobs,job)
        raise
    finally:
        result['clientMutations']=[op for op in operations if op['method']!='GET']
        write_json(output/'receipt.json',result)
        # Keep owning monitors alive until any cancellation has settled.
        deadline=time.monotonic()+20
        while job.exists() and time.monotonic()<deadline:
            process=jobs.processes.get(identity)
            if (process is None or process.poll() is not None) and not jobs.navigation.preparing(job):break
            time.sleep(1)
        server.shutdown();server.server_close();thread.join(5)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--worker-python',type=Path,default=ROOT/'.local-pilot/motor-amd-venv/Scripts/python.exe')
    args=parser.parse_args()
    result=run(args.source_input,args.output,args.worker_python)
    print(json.dumps({key:result[key] for key in ('outcome','seconds','automaticMethod','clientPrepareRequests','manualAdoption','sourcePoseEdits')}),flush=True)


if __name__=='__main__':main()
