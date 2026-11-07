"""Exploratory image-line VP hypotheses, no SfM pose or camera intrinsics input."""
import os,sys,time,json,hashlib,math
from pathlib import Path
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1')
sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import cv2,numpy as np
from scripts.pilot.resource_guard import windows_memory
cv2.setNumThreads(2)
base=Path('.local-pilot/scooter-targeted-gap-20261101-v2'); out=Path('.local-pilot/scooter-vp-calibration-20261101'); maskpath=Path('.local-pilot/scooter-precise-hud-20261101/mask.png'); started=time.monotonic()
def guard():
 m=windows_memory()
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*2**30 or time.monotonic()-started>53:raise RuntimeError('resource_or_time_guard')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
guard(); geom=json.loads((base/'geometry-0.json').read_text()); cameras=geom['cameras'];times=[0,3,10,15,19,20,21,23,27,30,33,35.49];selected=[]
for t in times:
 c=min(cameras,key=lambda x:(abs(x['ticks_90k']/90000-t),x['ticks_90k']))
 if c not in selected:selected.append(c)
mask=cv2.resize(cv2.imread(str(maskpath),0),(960,540),interpolation=cv2.INTER_NEAREST); rng=np.random.default_rng(20261101); rows=[]; panels=[]; images={}
for c in selected:
 guard();path=base/'prepared/images'/c['image'];images[str(path)]=sha(path);im=cv2.imread(str(path)); small=cv2.resize(im,(960,540)); gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
 lines=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0];lines=np.empty((0,4),np.float32) if lines is None else lines[:,0,:]
 length=np.linalg.norm(lines[:,2:]-lines[:,:2],axis=1); good=(length>=24)
 for t in np.linspace(0,1,9):
  xy=lines[:,:2]*(1-t)+lines[:,2:]*t;xx=np.clip(np.round(xy[:,0]).astype(int),0,959);yy=np.clip(np.round(xy[:,1]).astype(int),0,539);good &= (mask[yy,xx]>0)&(yy>=135)&(yy<450)
 lines=lines[good];length=length[good];order=np.argsort(-length)[:220];lines=lines[order]; length=length[order];mids=(lines[:,:2]+lines[:,2:])/2;direction=(lines[:,2:]-lines[:,:2])/length[:,None] if len(lines) else np.empty((0,2)); coeff=np.cross(np.column_stack((lines[:,:2],np.ones(len(lines)))),np.column_stack((lines[:,2:],np.ones(len(lines))))) if len(lines) else np.empty((0,3));available=np.ones(len(lines),bool);groups=[];colors=[(50,210,255),(120,255,100),(255,120,180)]
 for family in range(3):
  ids=np.flatnonzero(available)
  if len(ids)<8:break
  samples=rng.choice(ids,size=(600,2));best=None
  for a,b in samples:
   if a==b:continue
   v=np.cross(coeff[a],coeff[b]);
   if abs(v[2])<1e-7:continue
   vp=v[:2]/v[2]
   if not np.isfinite(vp).all() or np.linalg.norm(vp)>30000:continue
   w=vp-mids; denom=np.linalg.norm(w,axis=1); residual=np.abs(direction[:,0]*w[:,1]-direction[:,1]*w[:,0])/np.maximum(denom,1e-6);support=available&(residual<math.sin(math.radians(2)))
   score=float(np.minimum(length[support],100).sum())
   if best is None or score>best[0]:best=(score,support,vp,residual)
  if best is None or int(best[1].sum())<8:break
  _,support,vp,residual=best; fit=coeff[support];fit=fit/np.linalg.norm(fit[:,:2],axis=1)[:,None];u,s,vh=np.linalg.svd(fit,full_matrices=False);v=vh[-1];
  if abs(v[2])>1e-8:vp=v[:2]/v[2]
  w=vp-mids;denom=np.linalg.norm(w,axis=1);err=np.degrees(np.arcsin(np.clip(np.abs(direction[:,0]*w[:,1]-direction[:,1]*w[:,0])/np.maximum(denom,1e-6),0,1)))
  groups.append({'vp_xy_fullres':(vp*2).tolist(),'inliers':int(support.sum()),'median_angular_residual_deg':float(np.median(err[support])),'p90_angular_residual_deg':float(np.quantile(err[support],.9)),'normalized_fit_singular_values':s.tolist(),'distance_from_center_image_widths':float(np.linalg.norm(vp-[480,270])/960),'finite_near_enough':bool(np.linalg.norm(vp-[480,270])<5760)})
  for l in lines[support]:cv2.line(small,tuple(np.rint(l[:2]).astype(int)),tuple(np.rint(l[2:]).astype(int)),colors[family],2,cv2.LINE_AA)
  available &= ~support
 pairs=[]
 for i in range(len(groups)):
  for j in range(i+1,len(groups)):
   a=np.array(groups[i]['vp_xy_fullres'])-[960,540];b=np.array(groups[j]['vp_xy_fullres'])-[960,540];f2=-float(a@b)
   sensitivity=[]
   for dx,dy in [(0,0),(-48,0),(48,0),(0,-48),(0,48)]:
    aa=a-[dx,dy];bb=b-[dx,dy];value=-float(aa@bb)
    sensitivity.append({'principal_offset_xy':[dx,dy],'focal_px':math.sqrt(value) if value>0 else None})
   pairs.append({'families':[i+1,j+1],'hypothesis_f_px':math.sqrt(f2) if f2>0 else None,'f_squared_sign':'positive' if f2>0 else 'nonpositive','principal_point_sensitivity_not_confidence_interval':sensitivity,'assumed_orthogonal_not_verified':True,'both_finite_near_enough':groups[i]['finite_near_enough'] and groups[j]['finite_near_enough']})
 text=f"{c['image']} {c['ticks_90k']/90000:.2f}s lines {len(lines)} groups {'/'.join(str(g['inliers']) for g in groups)}";cv2.rectangle(small,(0,0),(960,35),(0,0,0),-1);cv2.putText(small,text,(8,24),cv2.FONT_HERSHEY_SIMPLEX,.63,(255,255,255),1,cv2.LINE_AA);panels.append(cv2.resize(small,(640,360)));rows.append({'image':c['image'],'ticks_90k':c['ticks_90k'],'segments_total':len(lines),'families':groups,'pair_hypotheses':pairs})
guard();grid=[]
for i in range(0,len(panels),3):
 row=panels[i:i+3]
 while len(row)<3:row.append(np.zeros_like(panels[0]))
 grid.append(np.concatenate(row,axis=1))
cv2.imwrite(str(out/'segments-contact.jpg'),np.concatenate(grid,axis=0),[cv2.IMWRITE_JPEG_QUALITY,85]);result={'status':'exploratory_no_accepted_focal','method':'LSD segments, HUD mask and fixed lower-image region; greedy independent two-line VP hypotheses; no Manhattan or orthogonality verification','assumptions':'pinhole, square pixels, principal point (960,540); orthogonal scene families NOT established','not_ground_truth':True,'selection_uses_sfm_poses':False,'source_frame_indices':'filenames bound to prepared source frames','input_sha256':images,'mask_sha256':sha(maskpath),'frames':rows,'elapsed_seconds':time.monotonic()-started,'references':['https://openaccess.thecvf.com/content_cvpr_2017/papers/Antunes_Unsupervised_Vanishing_Point_CVPR_2017_paper.pdf','https://openaccess.thecvf.com/content/ICCV2023/papers/Pautrat_Vanishing_Point_Estimation_in_Uncalibrated_Images_with_Prior_Gravity_Direction_ICCV_2023_paper.pdf'],'limitations':'Image-region filtering is not a semantic sky/world classifier. Greedy VP families can mix parallel/repeated facade lines, curves, signs and moving objects. Pair focal values are conditional hypotheses only; no uncertainty interval, no heldout validation, no recovered dynamic FOV.'};(out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps({'frames':len(rows),'elapsed':result['elapsed_seconds'],'counts':[len(r['families']) for r in rows]}))
