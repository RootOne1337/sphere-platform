import os,sys,json,math,statistics,pathlib
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,pycolmap as p
from scripts.pilot.reconstruct_route import model_assessment
from scripts.pilot.route_motion_audit import audit
root=pathlib.Path('.local-pilot/scooter-calf-orientation-gp-20261101');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');orig=json.loads(pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json').read_text());names=[c['image'] for c in orig['cameras']];hud=json.loads(pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json').read_text())['edges'];results={}
for label,path in [('source',base/'models/0'),('GP',root/'gp-model'),('fixedRBA',root/'fixed-r-ba-model')]:
 if not path.exists():continue
 rec=p.Reconstruction(path);geom,assess=model_assessment(rec,base/'prepared',166,0.,35.493);geom.update(execution_qualified=False,navigation_qualified=False,diagnostic_calffixed_orientation=(label!='source'));(root/(label+'-geometry.json')).write_text(json.dumps(geom));cams={c['image']:c for c in geom['cameras']};rat=[]
 for e in hud:
  a=cams.get(e['first_image']);b=cams.get(e['second_image']);d=e['hud_distance']
  if a and b and d and d>0:
   v=math.dist(a['center'],b['center'])/d
   if v>0:rat.append((e['edge_index'],v))
 fit=[v for i,v in rat if i<81];test=[v for i,v in rat if i>=81];s=statistics.median(fit) if fit else None;errs=[];behind=0;observations=0
 for pt in rec.points3D.values():
  for el in pt.track.elements:
   im=rec.images[el.image_id];cam=rec.cameras[im.camera_id];q=im.cam_from_world().rotation.matrix()@pt.xyz+im.cam_from_world().translation;observations+=1
   if q[2]<=0:behind+=1;continue
   f,cx,cy=cam.params;pred=np.array([f*q[0]/q[2]+cx,f*q[1]/q[2]+cy]);errs.append(float(np.linalg.norm(pred-im.point2D(el.point2D_idx).xy)))
 results[label]={'model_assessment':assess,'hud':{'edges':len(rat),'fit_count':len(fit),'test_count':len(test),'test_median_abs_log':statistics.median(abs(math.log(v/s)) for v in test) if test and s else None,'test_factor4':sum(v/s<.25 or v/s>4 for v in test) if test and s else None},'actual_reprojection':{'front_observations':len(errs),'all_observations':observations,'behind':behind,'mean_px':float(np.mean(errs)) if errs else None,'median_px':float(np.median(errs)) if errs else None,'p95_px':float(np.percentile(errs,95)) if errs else None},'motion_whole166':audit(geom),'motion_original163':audit({'cameras':[cams[n] for n in names if n in cams]}),'camera_params':next(iter(rec.cameras.values())).params.tolist()}
(root/'assessment.json').write_text(json.dumps({'models':results,'caveat':'Existing SIFT tracks selected by prior reconstruction; no independent pose truth. Calf rotations experimental fixed inputs; reprojection on same tracks, HUD same-video posthoc fit65/test60; arbitrary scale. No execution qualification.'},indent=2));
for label,x in results.items():print(label,'reproj',x['actual_reprojection'],'hud',x['hud'],'motion163',len(x['motion_original163']['rapid_reversals']),len(x['motion_original163']['speed_outliers']),flush=True)
