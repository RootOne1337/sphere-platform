import os,sys,pathlib,json,math,statistics,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
cv2.setNumThreads(2)
r=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');bp=pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json');base=json.loads(bp.read_text());new=json.loads((r/'geometry-0.json').read_text());bc={x['image']:x for x in base['cameras']};nc={x['image']:x for x in new['cameras']};assert all(f'{i:08d}.png' in nc for i in (492,496,497,498,499,500,504))
def ang(R):return float(np.degrees(np.arccos(np.clip((np.trace(R)-1)/2,-1,1))))
def summarise(cams,ordered):
 steps=[math.dist(cams[a]['center'],cams[b]['center']) for a,b in zip(ordered,ordered[1:])];idx=ordered.index('00000496.png');j=ordered.index('00000500.png');d=math.dist(cams[ordered[idx]]['center'],cams[ordered[j]]['center']);return {'median_step':statistics.median(steps),'orig496_500_displacement':d,'orig_interval_over_median_step':d/statistics.median(steps),'orig_496_500_seconds':(cams[ordered[j]]['ticks_90k']-cams[ordered[idx]]['ticks_90k'])/90000}
order=[x['image'] for x in base['cameras']];summary={'baseline_original_views':summarise(bc,order),'new_same_original_views':summarise(nc,order)};f=nc['00000496.png']['intrinsics']['fx'];K=np.array([[f,0,960],[0,f,540],[0,0,1.]])
with sqlite3.connect((r/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 ids={n:i for i,n in db.execute('select image_id,name from images')};xy={i:np.frombuffer(raw,np.float32).reshape(n,c)[:,:2] for i,n,c,raw in db.execute('select image_id,rows,cols,data from keypoints')};pairout=[]
 for x,y in [(492,496),(496,500),(500,504),(496,497),(497,498),(498,499),(499,500)]:
  a,b=f'{x:08d}.png',f'{y:08d}.png';i,j=ids[a],ids[b];z=db.execute('select rows,cols,data from two_view_geometries where pair_id=?',(min(i,j)*2147483647+max(i,j),)).fetchone();entry={'a':x,'b':y,'seconds_a':nc[a]['ticks_90k']/90000,'seconds_b':nc[b]['ticks_90k']/90000,'camera_step':math.dist(nc[a]['center'],nc[b]['center'])};A=np.asarray(nc[a]['camera_to_world'])[:,:3];B=np.asarray(nc[b]['camera_to_world'])[:,:3];R=B.T@A;entry['global_rotation_deg']=ang(R)
  if z and z[0]>=15:
   n,col,raw=z;mat=np.frombuffer(raw,np.uint32).reshape(n,col);mat=mat if i<j else mat[:,::-1];p0=xy[i][mat[:,0]];p1=xy[j][mat[:,1]];cv2.setRNGSeed(17);E,inliers=cv2.findEssentialMat(p0,p1,K,method=cv2.RANSAC,prob=.999,threshold=2.,maxIters=2000);entry['verified_matches']=n
   if E is not None and E.shape==(3,3):
    num,Rd,t,pm=cv2.recoverPose(E,p0,p1,K,mask=inliers.copy());entry.update(essential_inliers=int(inliers.sum()),positive_depth=int(num),direct_E_rotation_deg=ang(Rd),direct_vs_global_deg=ang(Rd@R.T))
  else:entry['verified_matches']=z[0] if z else 0
  pairout.append(entry)
summary.update(focal_px=f,pairs=pairout,note='Camera units arbitrary; normalized comparisons and HUD are same-video diagnostics. Direct E uses same verified correspondences and assumed model focal; not independent truth. Temporal neighborhood chosen after inspecting original jump.');(r/'gap-comparison.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
