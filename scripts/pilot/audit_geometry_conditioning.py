"""Paired motor sensitivity probe using real same-recording camera projections.

Only 'straight' carries the recorded camera trace; left/right are explicitly
counterfactual interventions on that same shape, not invented surveyed roads.
No input executor or Android session. Existing adapters reset history/RNG per
query: this tests first-frame image sensitivity, not closed-loop goal following.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from motor_worker.browser_teach import decoded_browser, validate_browser
from scripts.pilot import audit_motor_overlay as paired


def make_renderer(hints, size):
    import cv2 as cv
    import numpy as np

    def renderer(rgb, target_size, variant, style):
        if target_size != size or variant not in paired.VARIANTS or style not in {'cyan_line','yellow_arrow','green_corridor'}:
            raise ValueError('geometry_hint_probe_options')
        row=hints.get(hashlib.sha256(rgb).hexdigest())
        if row is None:
            raise ValueError('geometry_hint_source_not_bound')
        if variant in {'raw','raw_repeat'}:
            return rgb
        points=np.asarray(row['points'],np.float64).copy()
        if variant=='left':
            points[:,0]=.5-np.abs(points[:,0]-.5)
        elif variant=='right':
            points[:,0]=.5+np.abs(points[:,0]-.5)
        image=np.frombuffer(rgb,np.uint8).reshape(size,size,3).copy()
        pixels=np.rint(points*size).astype(np.int32)
        if style in {'cyan_line','green_corridor'}:
            cv.polylines(image,[pixels],False,(5,14,22),max(3,size//64),cv.LINE_AA)
            cv.polylines(image,[pixels],False,(97,234,216),max(1,size//128),cv.LINE_AA)
            for a,b in zip(pixels[:-1],pixels[1:]):
                delta=b-a
                if np.linalg.norm(delta)<4:
                    continue
                angle=np.arctan2(delta[1],delta[0])
                tail=np.array([[b[0]-np.cos(angle-.55)*6,b[1]-np.sin(angle-.55)*6],b,
                               [b[0]-np.cos(angle+.55)*6,b[1]-np.sin(angle+.55)*6]],np.int32)
                cv.polylines(image,[tail],False,(226,255,250),1,cv.LINE_AA)
        if style in {'yellow_arrow','green_corridor'}:
            # A separate direction instrument, never painted as a ground lane.
            center=np.array([size*.14,size*.80])
            radius=size*.12
            cv.circle(image,tuple(center.astype(int)),int(radius),(12,24,35),-1,cv.LINE_AA)
            yaw=float(row['yaw'])
            if variant=='left':
                yaw=-max(abs(yaw),.2)
            elif variant=='right':
                yaw=max(abs(yaw),.2)
            target=center+radius*.8*np.array([np.sin(yaw),-np.cos(yaw)])
            cv.arrowedLine(image,tuple(center.astype(int)),tuple(target.astype(int)),(255,227,100),max(2,size//100),cv.LINE_AA,tipLength=.35)
        return image.tobytes()
    return renderer


def prepare(capture_path, poses_path, route_path, route_sha256, output, size):
    import cv2 as cv
    import numpy as np

    from motor_worker.route_localization import SparseRoute

    output=Path(output)
    output.mkdir(exist_ok=False,parents=True)
    capture=validate_browser(capture_path)
    if Path(poses_path).stat().st_size>2*1024**2:
        raise ValueError('geometry_hint_pose_quota')
    report=json.loads(Path(poses_path).read_bytes())
    route=SparseRoute.load(Path(route_path), sha256=route_sha256)
    source_sha=hashlib.sha256(capture.originals['manifest.json']).hexdigest()
    if (report.get('capture_manifest_sha256')!=source_sha or report.get('offline_media_clock') is not True
            or route.source_capture_sha256!=source_sha or report.get('route_id')!=route.id):
        raise ValueError('geometry_hint_capture_binding')
    candidates=[]
    for row in report['samples']:
        pose=row['pose']
        points=pose.get('polyline_px',[])
        if (pose['state']!='localized' or len(points)<3 or row['source_index'] in route.source_frame_indices
                or pose.get('route_id') != route.id):
            continue
        points=np.asarray(points,np.float64)
        length=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())
        if length>=50:
            candidates.append((row,points,length))
    chosen=[]
    for row,points,length in sorted(candidates,key=lambda item:-item[2]):
        if all(abs(row['media_seconds']-old['seconds'])>=5 for old in chosen):
            chosen.append(dict(index=row['source_index'],seconds=row['media_seconds'],points=points.tolist(),pose=row['pose']))
        if len(chosen)==4:
            break
    if len(chosen)<3:
        raise ValueError('geometry_hint_insufficient_distinct_views')
    wanted={row['index']:row for row in chosen}
    hints,images={},[]
    for meta,decoded in decoded_browser(capture):
        row=wanted.get(meta['index'])
        if row is None:
            continue
        rgb=decoded.to_ndarray(format='rgb24')
        if hashlib.sha256(rgb.tobytes()).hexdigest()!=row['pose']['source_rgb_sha256']:
            raise ValueError('geometry_hint_query_rgb_changed')
        image=cv.resize(rgb,(size,size),interpolation=cv.INTER_AREA)
        # Yaw is from this actual projected route endpoint. Ground/body positions
        # remain uncalibrated; this is a visual-hint counterfactual experiment.
        points=np.asarray(row['points'])/[960,540]
        fx,_,cx,_=route.intrinsics
        yaw=float(np.arctan2(points[-1,0]*960-cx,fx))
        hints[hashlib.sha256(image.tobytes()).hexdigest()]=dict(points=points.tolist(),yaw=yaw,index=row['index'])
        path=output/f"source-{row['index']:05d}.png"
        if not cv.imwrite(str(path),cv.cvtColor(rgb,cv.COLOR_RGB2BGR)):
            raise ValueError('geometry_hint_source_write')
        images.append(str(path))
    provenance=dict(sourceManifestSha256=source_sha,poseReportSha256=hashlib.sha256(Path(poses_path).read_bytes()).hexdigest(),routeSha256=route_sha256,
        selected=[{k:v for k,v in row.items() if k!='pose'} for row in chosen],
        sameRecording=True,independentNewSession=False,groundRoute=False,physicalActions=0)
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return hints,images,provenance


async def main_async(args):
    from scripts.pilot.resource_guard import collect, evaluate

    if evaluate(collect(Path.cwd()),min_ram_gib=12):
        raise ValueError('geometry_hint_resource_guard')
    output=Path(args.output)
    if output.exists():
        raise ValueError('geometry_hint_output_exists')
    hints,images,provenance=prepare(args.capture,args.poses,args.route,args.route_sha256,output/'inputs',args.size)
    report=await paired.run(SimpleNamespace(python=args.python,script=args.script,adapter=args.adapter,image=images,
        size=args.size,seeds=args.seeds,style=['cyan_line','yellow_arrow','green_corridor'],output=output/'paired'),
        renderer=make_renderer(hints,args.size))
    report.update(inputProvenance=provenance,hintDerivedFromRecordedCameraGeometry=True,
        lineDerivedFromVerifiedRoute=False,groundRoute=False,closedLoopGoalFollowingTested=False,
        firstFrameResetProbe=True,textGoalConditioning=False,
        variantSemantics=dict(straight='actual_camera_trace',left='counterfactual_left',right='counterfactual_right'),
        styleSemantics=dict(cyan_line='attached_chevrons',yellow_arrow='direction_instrument',green_corridor='combined'))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('error','summary','physicalActions')}))
    return int(report.get('error') is not None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','poses','python','script','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--route',required=True)
    parser.add_argument('--route-sha256',required=True)
    parser.add_argument('--adapter',choices=sorted(paired.ADAPTERS),required=True)
    parser.add_argument('--size',type=int,choices=(192,256),required=True)
    parser.add_argument('--seeds',nargs='+',type=int,default=[17,29])
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__=='__main__':
    main()
