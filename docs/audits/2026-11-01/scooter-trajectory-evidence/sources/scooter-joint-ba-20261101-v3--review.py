import os,sys,time,pathlib,json,hashlib
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import numpy as np,cv2
cv2.setNumThreads(2);start=time.monotonic();G=1024**3;root=pathlib.Path('.local-pilot/scooter-joint-ba-20261101-v3');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2/geometry-0.json');files=[base,root/'data.npz',root/'comparison.json']+[root/n/'fit.npz' for n in ('w0','w05','w2')]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
before={str(p):sha(p) for p in files};m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*G;z=np.load(root/'data.npz');C0=z['centers'];P0=z['xyz'];ci=z['ci'];pi=z['pi'];uv=z['uv'];hold=z['hold'];R=z['R'];K=z['K'];ticks=z['ticks'];anchor=int(z['anchor']);L=float(z['anchor_distance']);geobase=json.loads(base.read_text());R0=np.array(geobase['cameras'][0]['camera_to_world'])[:,:3];Cfirst=np.array(geobase['cameras'][0]['center']);assert np.max(np.abs(C0[0]-Cfirst))<1e-7
models={'baseline':(C0,P0)}
for n in ('w0','w05','w2'):
 v=np.load(root/n/'fit.npz');models[n]=(v['centers'],v['points']);assert abs(np.linalg.norm(v['centers'][anchor]-v['centers'][0])-L)<1e-8
# Reprojection statistics, separately for training and held-out observations.
def score(C,P,subset):
 idx=np.flatnonzero(subset);c=ci[idx];p=pi[idx];q=np.einsum('nij,nj->ni',R[c],P[p]-C[c]);zv=q[:,2];valid=np.abs(zv)>1e-9;pred=np.zeros((len(idx),2));pred[valid,0]=K[c[valid],0,0]*q[valid,0]/zv[valid]+K[c[valid],0,2];pred[valid,1]=K[c[valid],1,1]*q[valid,1]/zv[valid]+K[c[valid],1,2];e=np.linalg.norm(pred-uv[idx],axis=1);return {'count':len(idx),'mean_px':float(np.mean(e[valid])),'median_px':float(np.median(e[valid])),'p95_px':float(np.percentile(e[valid],95)),'behind_or_zero_depth':int((zv<=1e-9).sum())}
comparison=json.loads((root/'comparison.json').read_text());data={'anchor_frame':geobase['cameras'][anchor]['image'],'anchor_distance_model_units':L,'coordinate_frame':'camera0 center origin and camera0 x/z axes; x/z projection of camera centers, not topdown physical map','all_rotations_intrinsics_fixed':True,'cases':{},'most_changed_intervals':{},'limits':'Diagnostic partial point subset; projected line connects reconstructed samples only, not a proven road or motion. Values in model units, no uncertainty or ground truth.'}
for n,(C,P) in models.items():data['cases'][n]={'train':score(C,P,~hold),'heldout':score(C,P,hold),'first_camera_unchanged':bool(np.linalg.norm(C[0]-Cfirst)<1e-7),'anchor_distance':float(np.linalg.norm(C[anchor]-C[0])),'max_step':float(np.linalg.norm(np.diff(C,axis=0),axis=1).max())}
w0=models['w0'][0];s0=np.linalg.norm(np.diff(w0,axis=0),axis=1)
for n in ('w05','w2'):
 C=models[n][0];si=np.linalg.norm(np.diff(C,axis=0),axis=1);order=np.argsort(np.abs(si-s0))[::-1][:8];data['most_changed_intervals'][n]=[{'image_a':geobase['cameras'][i]['image'],'image_b':geobase['cameras'][i+1]['image'],'start_s':float(ticks[i]/90000),'end_s':float(ticks[i+1]/90000),'w0_step':float(s0[i]),'candidate_step':float(si[i]),'delta_step':float(si[i]-s0[i])} for i in order];data['cases'][n]['max_step_reduction_vs_w0_percent']=100*(data['cases']['w0']['max_step']-data['cases'][n]['max_step'])/data['cases']['w0']['max_step'];prior=comparison['models'][n]['velocity_change_normalized']['p95'];v0=comparison['models']['w0']['velocity_change_normalized']['p95'];data['cases'][n]['velocity_change_p95_reduction_vs_w0_percent']=100*(v0-prior)/v0
# Consistent limits, same camera0 reference and equal metric units across all four panels.
projected={}
for n,(C,P) in models.items():projected[n]=((C-Cfirst)@R0)[:,[0,2]]
stack=np.vstack(list(projected.values()));low=stack.min(axis=0);high=stack.max(axis=0);mid=(low+high)/2;span=max(float((high-low).max())*1.12,1.);low=mid-span/2;high=mid+span/2
canvas=np.full((1030,1600,3),250,np.uint8);cv2.putText(canvas,'Camera centers projected to first camera X/Z plane - diagnostic, not road geometry',(35,37),cv2.FONT_HERSHEY_SIMPLEX,.74,(30,30,30),2,cv2.LINE_AA)
cv2.putText(canvas,f'All panels same axes and scale; anchor = {L:.3f} model units; baseline fit used observations later held out',(35,65),cv2.FONT_HERSHEY_SIMPLEX,.5,(60,60,60),1,cv2.LINE_AA)
positions={'baseline':(30,95),'w0':(815,95),'w05':(30,550),'w2':(815,550)};titles={'baseline':'Before (baseline fit used all observations)','w0':'w=0 control; ftol termination','w05':'w=0.5; ftol termination','w2':'w=2; NOT CONVERGED'}
for n,(x0,y0) in positions.items():
 x1,y1=x0+755,y0+420;cv2.rectangle(canvas,(x0,y0),(x1,y1),(195,195,195),1);cv2.putText(canvas,titles[n],(x0+12,y0+25),cv2.FONT_HERSHEY_SIMPLEX,.55,(25,25,25),1,cv2.LINE_AA);area=(x0+125,y0+45,x0+625,y0+390);ax1,ay1,ax2,ay2=area
 for j in range(5):
  gx=int(ax1+(ax2-ax1)*j/4);gy=int(ay1+(ay2-ay1)*j/4);cv2.line(canvas,(gx,ay1),(gx,ay2),(231,231,231),1);cv2.line(canvas,(ax1,gy),(ax2,gy),(231,231,231),1)
 scale=min((ax2-ax1)/span,(ay2-ay1)/span);cx=(ax1+ax2)/2;cy=(ay1+ay2)/2;arr=projected[n];pixel=np.column_stack([cx+(arr[:,0]-mid[0])*scale,cy-(arr[:,1]-mid[1])*scale]).round().astype(np.int32)
 cv2.polylines(canvas,[pixel.reshape(-1,1,2)],False,(170,85,35),2,cv2.LINE_AA)
 for p in pixel:cv2.circle(canvas,tuple(p),2,(170,85,35),-1)
 cv2.circle(canvas,tuple(pixel[0]),6,(40,160,30),-1);cv2.circle(canvas,tuple(pixel[-1]),6,(25,25,220),-1)
 d=data['cases'][n];cv2.putText(canvas,f'held-out mean/p95: {d["heldout"]["mean_px"]:.3f}/{d["heldout"]["p95_px"]:.3f}px',(x0+10,y0+412),cv2.FONT_HERSHEY_SIMPLEX,.46,(40,40,40),1,cv2.LINE_AA)
 cv2.putText(canvas,'X (first camera)',(x0+310,y0+404),cv2.FONT_HERSHEY_SIMPLEX,.37,(80,80,80),1);cv2.putText(canvas,'Z',(x0+80,y0+210),cv2.FONT_HERSHEY_SIMPLEX,.4,(80,80,80),1)
cv2.putText(canvas,'Green = first frame; red = last. Lines connect sampled camera centers; no road or between-frame motion is verified.',(35,1010),cv2.FONT_HERSHEY_SIMPLEX,.48,(50,50,50),1,cv2.LINE_AA)
after={str(p):sha(p) for p in files};assert before==after and time.monotonic()-start<30;data.update(source_hashes_before=before,source_hashes_after=after,source_unchanged=True,seconds=time.monotonic()-start);(root/'review-comparison.json').write_text(json.dumps(data,indent=2));cv2.imwrite(str(root/'review-comparison.png'),canvas);print(json.dumps({'cases':data['cases'],'most_changed_intervals':data['most_changed_intervals'],'elapsed':data['seconds']},indent=2))
