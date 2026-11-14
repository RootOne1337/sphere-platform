"""Offline diagnostic on all available model components; no auto-selection."""
import os,sys,json,pathlib,math,statistics,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import numpy as np,cv2,pycolmap as p
from scripts.pilot.route_motion_audit import audit
cv2.setNumThreads(4);root=pathlib.Path('.local-pilot/scooter-temporal-flow-full-20261101/mapping');names=[c['image'] for c in json.loads(pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json').read_text())['cameras']];hud=json.loads(pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json').read_text())['edges'];out=[];stored=[(path,p.Reconstruction(path)) for path in sorted((root/'models').iterdir()) if path.is_dir()]
with sqlite3.connect((root/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 ids={n:i for i,n in db.execute('select image_id,name from images')};xy={i:np.frombuffer(raw,np.float32).reshape(n,c)[:,:2] for i,n,c,raw in db.execute('select image_id,rows,cols,data from keypoints')}
 for path in sorted(root.glob('geometry-*.json')):
  m=windows_memory()
  if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*1024**3:raise RuntimeError('memory_guard')
  identity=path.stem.split('-')[-1];g=json.loads(path.read_text());cams={c['image']:c for c in g['cameras']};matches=[(folder,model) for folder,model in stored if {im.name for im in model.images.values() if im.has_pose}==set(cams)];assert len(matches)==1,(identity,'model_geometry_binding_failed');modeldir,rec=matches[0];rat=[]
  for e in hud:
   a=cams.get(e['first_image']);b=cams.get(e['second_image']);d=e['hud_distance']
   if a and b and d and d>0:
    v=math.dist(a['center'],b['center'])/d
    if v>0:rat.append((e['edge_index'],v))
  fit=[v for i,v in rat if i<81];test=[v for i,v in rat if i>=81];scale=statistics.median(fit) if fit else None;behind=obs=duplicates=duplicate_images=nonfinite=0;err=[]
  for pt in rec.points3D.values():
   seen=set();seen_images=set()
   for el in pt.track.elements:
    key=(el.image_id,el.point2D_idx);duplicates+=int(key in seen);seen.add(key);duplicate_images+=int(el.image_id in seen_images);seen_images.add(el.image_id);im=rec.images[el.image_id];cam=rec.cameras[im.camera_id];q=im.cam_from_world().rotation.matrix()@pt.xyz+im.cam_from_world().translation;obs+=1
    if not np.isfinite(q).all():nonfinite+=1;continue
    if q[2]<=0:behind+=1;continue
    f,cx,cy=cam.params;pred=np.array([f*q[0]/q[2]+cx,f*q[1]/q[2]+cy]);value=float(np.linalg.norm(pred-im.point2D(el.point2D_idx).xy));nonfinite+=int(not math.isfinite(value));err.extend([value] if math.isfinite(value) else [])
  f,_,_=next(iter(rec.cameras.values())).params;K=np.array([[f,0,960],[0,f,540],[0,0,1.]]);pairs=[];ordered=[c['image'] for c in g['cameras']]
  for a,b in zip(ordered,ordered[1:]):
   i,j=ids[a],ids[b];row={'first':a,'second':b};z=db.execute('select rows,cols,data from two_view_geometries where pair_id=?',(min(i,j)*2147483647+max(i,j),)).fetchone();row['verified_matches']=z[0] if z else 0
   if z and z[0]>=15:
    n,col,raw=z;mat=np.frombuffer(raw,np.uint32).reshape(n,col);mat=mat if i<j else mat[:,::-1];cv2.setRNGSeed(17);E,mask=cv2.findEssentialMat(xy[i][mat[:,0]],xy[j][mat[:,1]],K,method=cv2.RANSAC,prob=.999,threshold=2.,maxIters=2000)
    if E is not None and E.shape==(3,3):
     num,R,t,_=cv2.recoverPose(E,xy[i][mat[:,0]],xy[j][mat[:,1]],K,mask=mask.copy());A=np.asarray(cams[a]['camera_to_world'])[:,:3];B=np.asarray(cams[b]['camera_to_world'])[:,:3];delta=R@(B.T@A).T;row.update(positive_depth=int(num),direct_vs_global_deg=float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1)))))
   pairs.append(row)
  angles=[r['direct_vs_global_deg'] for r in pairs if 'direct_vs_global_deg'in r];present=[cams[n] for n in names if n in cams];out.append({'model':identity,'stored_model_directory':str(modeldir),'model_geometry_binding':'exact image-name set','registered':rec.num_reg_images(),'points':rec.num_points3D(),'common_original163':len(present),'shared_focal_px':float(f),'reprojection':{'finite_front_count':len(err),'all_observations':obs,'behind':behind,'nonfinite_count':nonfinite,'mean_px':float(np.mean(err)) if err else None,'median_px':float(np.median(err)) if err else None,'p95_px':float(np.percentile(err,95)) if err else None,'duplicate_track_observations':duplicates,'duplicate_track_images':duplicate_images},'hud':{'edges':len(rat),'fit':len(fit),'test':len(test),'test_median_abs_log':statistics.median(abs(math.log(v/scale)) for v in test) if test and scale else None,'test_factor4':sum(v/scale<.25 or v/scale>4 for v in test) if test and scale else None,'warning':'Partial counts are not comparable to full 125-edge split.'},'motion_whole':audit(g),'motion_original_present':audit({'cameras':present}) if len(present)>=2 else None,'direct_E':{'intervals_examined':len(pairs),'estimated':len(angles),'median_deg':float(np.median(angles)) if angles else None,'p95_deg':float(np.percentile(angles,95)) if angles else None,'over_10deg':sum(v>10 for v in angles),'pairs':pairs}})
(root/'assessment.json').write_text(json.dumps({'models':out,'caveat':'No independent pose truth. E and global use same source matches and focal, HUD same-video posthoc. Gaps not imputed; partial geometry is not full route.'},indent=2));print('assessed',len(out),flush=True)
