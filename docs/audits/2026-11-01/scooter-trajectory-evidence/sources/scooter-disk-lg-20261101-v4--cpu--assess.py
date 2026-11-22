import os,sys,pathlib,json,math,statistics,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import numpy as np,cv2,pycolmap as p
from scripts.pilot.route_motion_audit import audit
cv2.setNumThreads(4);root=pathlib.Path('.local-pilot/scooter-disk-lg-20261101-v4/cpu');g=json.loads((root/'geometry-0.json').read_text());orig=json.loads(pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json').read_text());names=[c['image'] for c in orig['cameras']];cams={c['image']:c for c in g['cameras']};assert all(n in cams for n in names);hud=json.loads(pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json').read_text())['edges'];rat=[]
for e in hud:
 a=cams.get(e['first_image']);b=cams.get(e['second_image']);d=e['hud_distance']
 if a and b and d and d>0:
  x=math.dist(a['center'],b['center'])/d
  if x>0:rat.append((e['edge_index'],x))
fit=[v for i,v in rat if i<81];test=[v for i,v in rat if i>=81];scale=statistics.median(fit);hudstats={'edges':len(rat),'fit_count':len(fit),'test_count':len(test),'test_median_abs_log':statistics.median(abs(math.log(x/scale)) for x in test),'test_factor4':sum(x/scale<.25 or x/scale>4 for x in test),'edge_ids':[i for i,v in rat]}
rec=p.Reconstruction(root/'models/0');camera=next(iter(rec.cameras.values()));K=camera.calibration_matrix();behind=observations=0
for pt in rec.points3D.values():
 for el in pt.track.elements:
  im=rec.images[el.image_id];q=im.cam_from_world().rotation.matrix()@pt.xyz+im.cam_from_world().translation;observations+=1;behind+=int(q[2]<=0)
def angle(R):return float(np.degrees(np.arccos(np.clip((np.trace(R)-1)/2,-1,1))))
pairout=[];ordered=[c['image'] for c in g['cameras']]
with sqlite3.connect((root/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 ids={n:i for i,n in db.execute('select image_id,name from images')};xy={i:np.frombuffer(raw,np.float32).reshape(n,c)[:,:2] for i,n,c,raw in db.execute('select image_id,rows,cols,data from keypoints')}
 for index,(a,b) in enumerate(zip(ordered,ordered[1:])):
  if index%10==0:
   m=windows_memory()
   if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*1024**3:break
  i,j=ids[a],ids[b];z=db.execute('select rows,cols,data from two_view_geometries where pair_id=?',(min(i,j)*2147483647+max(i,j),)).fetchone();row={'first':a,'second':b,'verified_matches':z[0] if z else 0};A=np.asarray(cams[a]['camera_to_world'])[:,:3];B=np.asarray(cams[b]['camera_to_world'])[:,:3];Rg=B.T@A
  if z and z[0]>=15:
   n,col,raw=z;mat=np.frombuffer(raw,np.uint32).reshape(n,col);mat=mat if i<j else mat[:,::-1];p0=xy[i][mat[:,0]];p1=xy[j][mat[:,1]];cv2.setRNGSeed(17);E,mask=cv2.findEssentialMat(p0,p1,K,method=cv2.RANSAC,prob=.999,threshold=2.,maxIters=2000)
   if E is not None and E.shape==(3,3):
    num,R,t,_=cv2.recoverPose(E,p0,p1,K,mask=mask.copy());row.update(essential_inliers=int(mask.sum()),positive_depth=int(num),direct_vs_global_deg=angle(R@Rg.T))
  pairout.append(row)
angles=[r['direct_vs_global_deg'] for r in pairout if 'direct_vs_global_deg'in r];result={'hud':hudstats,'motion_whole166':audit(g),'motion_original163':audit({'cameras':[cams[n] for n in names]}),'shared_focal_px':float(camera.params[0]),'triangulated_observations':observations,'behind_camera':behind,'direct_E_audit':{'tested_adjacent_intervals':len(pairout),'estimated':len(angles),'median_disagreement_deg':float(np.median(angles)) if angles else None,'p95_disagreement_deg':float(np.percentile(angles,95)) if angles else None,'over_10deg':sum(x>10 for x in angles),'pairs':pairout},'caveat':'E and SfM use same source/matches and estimated shared focal, not independent pose truth. HUD 125 edges are same-video posthoc, fit65/test60 for scale. GPU matching method and resolution differ from SIFT baseline.'};(root/'assessment.json').write_text(json.dumps(result,indent=2));print('hud',hudstats,'direct',len(angles),'above10',sum(x>10 for x in angles),'behind',behind,'of',observations,'focal',camera.params[0],flush=True)

