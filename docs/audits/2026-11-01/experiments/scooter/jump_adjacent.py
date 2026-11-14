"""Five real source frames: bounded LK/essential comparison, no device control."""
import os,sys,json,hashlib,time,traceback
from pathlib import Path
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
from motor_worker.browser_teach import validate_browser,decoded_browser
from scripts.pilot.resource_guard import windows_memory
cv2.setNumThreads(2);root=Path('.local-pilot/scooter-jump-adjacent-20261101');source=Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');maskpath=Path('.local-pilot/scooter-precise-hud-20261101/mask.png');G=1024**3;start=time.monotonic()
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def guard():
 m=windows_memory();r=m['availableRamBytes'];c=m['commitLimitBytes']-m['committedBytes']
 if min(r,c)<4.5*G:raise RuntimeError(f'host_guard:ram={r}:commit={c}')
 if time.monotonic()-start>42:raise TimeoutError('deadline')
def deg(R):return float(np.degrees(np.arccos(np.clip((np.trace(R)-1)/2,-1,1))))
def estimate(x,y,K):
 if len(x)<40:return {'status':'insufficient_tracks','tracks':len(x)},None
 cv2.setRNGSeed(17);E,mask=cv2.findEssentialMat(x,y,K,method=cv2.RANSAC,prob=.999,threshold=1.,maxIters=1000)
 if E is None or E.shape!=(3,3) or mask is None:return {'status':'essential_failed','tracks':len(x)},None
 n=int(np.count_nonzero(mask));positive,R,t,posemask=cv2.recoverPose(E,x,y,K,mask=mask.copy());xy=x[mask.ravel().astype(bool)];cells=int((np.histogram2d(xy[:,0],xy[:,1],bins=(8,4),range=((0,960),(0,540)))[0]>0).sum())
 result={'status':'estimate_only' if n>=30 and positive>=20 and positive/max(n,1)>=.4 and cells>=6 else 'unobservable_by_diagnostic_gate','tracks':len(x),'ransac_inliers':n,'positive_depth':int(positive),'occupied_8x4':cells,'rotation_degrees':deg(R),'translation_direction_unscaled':t.ravel().tolist(),'rotation_matrix':R.tolist()}
 return result,R if result['status']=='estimate_only' else None
def track(g0,g1,points,mask):
 if len(points)==0:return points,np.zeros(0,bool),np.empty(0),{'input':0}
 points=np.ascontiguousarray(points,dtype=np.float32).reshape(-1,1,2);q,st,_=cv2.calcOpticalFlowPyrLK(g0,g1,points,None,winSize=(31,31),maxLevel=4);back,st2,_=cv2.calcOpticalFlowPyrLK(g1,g0,q,None,winSize=(31,31),maxLevel=4)
 a=points.reshape(-1,2);b=q.reshape(-1,2);err=np.linalg.norm(a-back.reshape(-1,2),axis=1)*2;finite=np.isfinite(b).all(axis=1)&np.isfinite(err);within=finite&(b[:,0]>=0)&(b[:,0]<960)&(b[:,1]>=0)&(b[:,1]<540)
 status=(st.ravel()>0)&(st2.ravel()>0);fbpass=status&within&(err<=1.5);clipped=np.rint(np.nan_to_num(b,nan=0)).astype(int);clipped[:,0]=np.clip(clipped[:,0],0,959);clipped[:,1]=np.clip(clipped[:,1],0,539);allowed=mask[clipped[:,1],clipped[:,0]]>0;good=fbpass&allowed
 return b,good,err,{'input':len(points),'lk_status_both':int(status.sum()),'in_bounds':int(within.sum()),'fb_pass_before_mask':int(fbpass.sum()),'excluded_by_destination_mask_after_fb':int((fbpass&~allowed).sum())}
def detect(img,mask):
 pts=cv2.goodFeaturesToTrack(img,maxCorners=1600,qualityLevel=.01,minDistance=6,mask=mask,blockSize=3)
 return np.empty((0,2),np.float32) if pts is None else pts.reshape(-1,2)
try:
 inputs=[source/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[maskpath];before={str(v):sha(v) for v in inputs}
 capture=validate_browser(source);target=set(range(496,501));frames={};binding={};decoded=0
 for row,frame in decoded_browser(capture):
  decoded+=1
  if row['index'] in target:
   if frame.pts!=row['relative_ticks_90k']:raise RuntimeError('decoded_pts_mismatch')
   rgb=frame.to_ndarray(format='rgb24');frames[row['index']]=cv2.cvtColor(cv2.resize(rgb,(960,540)),cv2.COLOR_RGB2GRAY);binding[str(row['index'])]={'relative_ticks_90k':row['relative_ticks_90k'],'access_unit_sha256':row['sha256'],'pts':frame.pts}
  if decoded%100==0:guard()
 if set(frames)!=target or decoded!=901:raise RuntimeError('source_decode_incomplete')
 mask=cv2.resize(cv2.imread(str(maskpath),0),(960,540),interpolation=cv2.INTER_NEAREST);K=np.array([[603.2398818704738/2,0,480],[0,603.2398818704738/2,270],[0,0,1]],dtype=np.float64)
 rows=[];rotations=[]
 for i in range(496,500):
  guard();points=detect(frames[i],mask);q,ok,fb,diag=track(frames[i],frames[i+1],points,mask);good=points[ok];other=q[ok];result,R=estimate(good,other,K)
  row={'first':i,'second':i+1,'ticks':[binding[str(i)]['relative_ticks_90k'],binding[str(i+1)]['relative_ticks_90k']],'detected':len(points),'fb_valid_and_masked':int(ok.sum()),'tracking_diagnostics':diag,'retained_fraction':float(ok.mean()) if len(ok) else 0,'median_flow_original_px':float(np.median(np.linalg.norm(other-good,axis=1))*2) if len(good) else None,'essential':result};rows.append(row);rotations.append(R)
 points=detect(frames[496],mask);direct,ok,fb,direct_diag=track(frames[496],frames[500],points,mask);de,dr=estimate(points[ok],direct[ok],K)
 initial=points.copy();current=points.copy();active=np.ones(len(points),dtype=bool);chain_counts=[]
 for i in range(496,500):
  indices=np.flatnonzero(active);nextpos,valid,errs,_=track(frames[i],frames[i+1],current[indices],mask);active[indices[~valid]]=False;current[indices[valid]]=nextpos[valid];chain_counts.append(int(active.sum()))
 ce,cr=estimate(initial[active],current[active],K);compose=None
 if all(R is not None for R in rotations):
  compose=np.eye(3)
  for R in rotations:compose=R@compose
 def difference(a,b):return deg(a@b.T) if a is not None and b is not None else None
 after={str(v):sha(v) for v in inputs}
 if before!=after:raise RuntimeError('source_hash_changed')
 report={'status':'complete','frames_decoded_and_access_unit_hash_verified':decoded,'binding':binding,'source_sha256_before':before,'source_sha256_after':after,'source_unchanged':True,'opencv_version':cv2.__version__,'scale':0.5,'focal_assumption_original_px':603.2398818704738,'features':'Shi-Tomasi max1600, original HUD allowed mask, LK 31x31 maxLevel=4, forward-backward <=1.5 original px, mask at both ends','diagnostic_gate':'at least 40 tracks, 30 essential inliers, 20 positive-depth, 40% positive of inliers and 6 occupied cells; not an observability proof','adjacent':rows,'direct_496_to_500':{'detected':len(points),'retained':int(ok.sum()),'tracking_diagnostics':direct_diag,'essential':de},'chained_496_to_500':{'detected':len(points),'survivors_after_each':chain_counts,'essential':ce},'rotation_composed_adjacent_deg':deg(compose) if compose is not None else None,'rotation_direct_vs_composed_deg':difference(dr,compose),'rotation_chain_vs_composed_deg':difference(cr,compose),'rotation_chain_vs_direct_deg':difference(cr,dr),'elapsed_s':time.monotonic()-start,'limitations':'Same video and approximate focal; rotation results share optical flow inputs. Essential geometry may be degenerate despite numerical support and positive depth. No metric translation, absolute heading, ground truth, vehicle trajectory, or evidence that a match is correct. Different detectors/retention make raw counts not a controlled matching quality comparison.'}
 (root/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False));print(json.dumps(report,indent=2),flush=True)
except Exception as e:
 m=windows_memory();r={'status':'failed','type':type(e).__name__,'message':str(e)[:700],'elapsed_s':time.monotonic()-start,'free_ram':m['availableRamBytes'],'free_commit':m['commitLimitBytes']-m['committedBytes'],'traceback':[{'file':Path(x.filename).name,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(e.__traceback__)]};(root/'failure.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);raise SystemExit(1)
