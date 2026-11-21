"""Read-only 2D/3D evidence for one outlier and adjacent control pairs."""
import os,sys,json,hashlib,sqlite3,time,traceback
from pathlib import Path
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2,pycolmap as p
from scripts.pilot.resource_guard import windows_memory
cv2.setNumThreads(2)
out=Path('.local-pilot/scooter-jump-forensics-20261101');root=Path('.local-pilot/scooter-stage-global-focal-20261101');database=root/'database.db';model=root/'models/0';prepared=Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared/images');maskfile=Path('.local-pilot/scooter-precise-hud-20261101/mask.png');job=Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');G=1024**3;start=time.monotonic()
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def guard():
 m=windows_memory();ram=m['availableRamBytes'];commit=m['commitLimitBytes']-m['committedBytes']
 if min(ram,commit)<4.5*G:raise RuntimeError(f'host_guard:ram={ram}:commit={commit}')
 if time.monotonic()-start>42:raise TimeoutError('internal_deadline')
try:
 geom=json.loads((root/'geometry-0.json').read_text());cams=geom['cameras']; names=[c['image'] for c in cams];motion=json.loads((root/'report.json').read_text())['models'][0]['motion'];bad=motion['speed_outliers'];assert len(bad)==1
 i=names.index(bad[0]['image']);assert 1<=i<len(names)-1
 pairnames=[(names[i-2],names[i-1]),(names[i-1],names[i]),(names[i],names[i+1])];files=[database,maskfile,job/'video.h264',root/'geometry-0.json']+[model/n for n in ('cameras.bin','images.bin','points3D.bin','frames.bin','rigs.bin')]+[prepared/n for n in sorted(set(sum(([a,b] for a,b in pairnames),[])))]
 before={str(q):sha(q) for q in files};mask=cv2.imread(str(maskfile),0);rec=p.Reconstruction(model);images_by_name={im.name:im for im in rec.images.values()};camera=next(iter(rec.cameras.values()));K=np.array([[camera.params[0],0,camera.params[1]],[0,camera.params[0],camera.params[2]],[0,0,1]])
 with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
  ids={name:id for id,name in db.execute('select image_id,name from images')};kps={id:np.frombuffer(raw,dtype='<f4').reshape(rows,cols)[:,:2].copy() for id,rows,cols,raw in db.execute('select image_id,rows,cols,data from keypoints')}
  records=[];canvases=[]
  for j,(a,b) in enumerate(pairnames):
   guard();aid,bid=ids[a],ids[b];pid=min(aid,bid)*2147483647+max(aid,bid);found=db.execute('select rows,cols,data from two_view_geometries where pair_id=?',(pid,)).fetchone()
   if not found or found[1]!=2:raise RuntimeError('inlier_pair_absent')
   n,cols,blob=found;m=np.frombuffer(blob,dtype='<u4').reshape(n,cols).copy()
   if aid>bid:m=m[:,::-1]
   pa=kps[aid][m[:,0]];pb=kps[bid][m[:,1]];im1=cv2.imread(str(prepared/a));im2=cv2.imread(str(prepared/b));g1=cv2.cvtColor(cv2.resize(im1,(960,540)),cv2.COLOR_BGR2GRAY);g2=cv2.cvtColor(cv2.resize(im2,(960,540)),cv2.COLOR_BGR2GRAY)
   x=((pa-.5)*.5).astype(np.float32).reshape(-1,1,2);dest,ok,_=cv2.calcOpticalFlowPyrLK(g1,g2,x,None,winSize=(21,21),maxLevel=3);back,ok2,_=cv2.calcOpticalFlowPyrLK(g2,g1,dest,None,winSize=(21,21),maxLevel=3)
   fb=np.linalg.norm(x.reshape(-1,2)-back.reshape(-1,2),axis=1)*2;err=np.linalg.norm(dest.reshape(-1,2)-(pb-.5)*.5,axis=1)*2;good=(ok.ravel()>0)&(ok2.ravel()>0)&np.isfinite(fb)&np.isfinite(err)&(fb<=1.5)
   def allowed(q):
    x=np.clip(np.floor(q[:,0]).astype(int),0,1919);y=np.clip(np.floor(q[:,1]).astype(int),0,1079);return mask[y,x]!=0
   def occ(q):return int((np.histogram2d(q[:,0],q[:,1],bins=(8,4),range=((0,1920),(0,1080)))[0]>0).sum())
   ia,ib=images_by_name[a],images_by_name[b];same=[];different=0;one=0;none=0;reproj=[]
   for z,(u,v) in enumerate(m):
    x0=ia.point2D(int(u));x1=ib.point2D(int(v));ha=x0.has_point3D();hb=x1.has_point3D()
    if ha and hb and x0.point3D_id==x1.point3D_id:
     point=rec.points3D[x0.point3D_id]; xyz=point.xyz;pc0=ia.cam_from_world()*xyz;pc1=ib.cam_from_world()*xyz;uv0=camera.img_from_cam(pc0);uv1=camera.img_from_cam(pc1)
     if uv0 is not None and uv1 is not None:reproj.append([z,float(np.linalg.norm(uv0-pa[z])),float(np.linalg.norm(uv1-pb[z]))])
     same.append(z)
    elif ha and hb:different+=1
    elif ha or hb:one+=1
    else:none+=1
   visual=np.concatenate([cv2.resize(im1,(960,540)),cv2.resize(im2,(960,540))],axis=1)
   chosen=np.linspace(0,max(0,n-1),min(n,100),dtype=int)
   for z in chosen:
    xy0=tuple(np.rint((pa[z]-.5)*.5).astype(int));xy1=tuple((np.rint((pb[z]-.5)*.5)+[960,0]).astype(int));color=(70,200,255);cv2.line(visual,xy0,xy1,color,1,cv2.LINE_AA);cv2.circle(visual,xy0,2,(0,255,0),-1);cv2.circle(visual,xy1,2,(0,255,0),-1)
   cv2.putText(visual,('CONTROL' if j!=1 else 'JUMP')+' '+a+' -> '+b+f'  verified={n}',(10,25),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2,cv2.LINE_AA);canvases.append(visual)
   candidates=sorted(np.flatnonzero(good),key=lambda k:float(err[k]),reverse=True)[:8];examples=[]
   for z in candidates:
    examples.append({'inlier_index':int(z),'feature_indices':m[z].tolist(),'source_xy_colmap':pa[z].tolist(),'target_xy_colmap':pb[z].tolist(),'lk_target_xy_image':(dest[z,0]*2).tolist(),'lk_forward_backward_error_px':float(fb[z]),'lk_to_match_error_px':float(err[z]),'same_reconstructed_3d_point':int(z) in same})
   r={'label':'jump' if j==1 else 'control','first':a,'second':b,'first_seconds':cams[i-2+j]['ticks_90k']/90000,'second_seconds':cams[i-1+j]['ticks_90k']/90000,'estimated_camera_step_units':float(np.linalg.norm(np.asarray(cams[i-1+j]['center'])-np.asarray(cams[i-2+j]['center']))),'verified_2d_matches':int(n),'both_hud_allowed':int((allowed(pa)&allowed(pb)).sum()),'both_top_quarter_y_lt_270':int(((pa[:,1]<270)&(pb[:,1]<270)).sum()),'occupied_8x4':[occ(pa),occ(pb)],'same_3d_point':len(same),'different_3d_points':different,'one_3d_point':one,'neither_3d_point':none,'same_3d_reprojection_error_median_px':float(np.median(np.asarray(reproj)[:,1:])) if reproj else None,'lk_tested':int(len(x)),'lk_forward_backward_valid':int(good.sum()),'lk_match_error_median_px_among_valid':float(np.median(err[good])) if good.any() else None,'lk_disagree_over_5px_among_valid':int(((err>5)&good).sum()),'lk_examples_high_disagreement':examples};records.append(r);print(json.dumps({'pair':[a,b],'count':n,'lk_valid':int(good.sum())}),flush=True)
 cv2.imwrite(str(out/'correspondences.jpg'),np.concatenate(canvases,axis=0),[cv2.IMWRITE_JPEG_QUALITY,90]);after={str(q):sha(q) for q in files}
 if before!=after:raise RuntimeError('source_changed')
 report={'status':'complete','outlier':bad[0],'camera_intrinsics':camera.params.tolist(),'pairs':records,'inputs_sha256_before':before,'inputs_sha256_after':after,'source_unchanged':before==after,'elapsed_s':time.monotonic()-start,'limits':'Verified graph means model-estimated two-view inliers, not truth. Top-quarter is image location, not semantic sky; mask is capture-specific HUD proposal. LK can fail or track different local appearance even when forward-backward consistent. Reprojection errors are fitted on the same reconstruction; not heldout accuracy. Three adjacent pairs, no causal proof of erroneous correspondences or metric scale.'}
 (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False));print(json.dumps({'status':'complete','elapsed_s':report['elapsed_s']}),flush=True)
except Exception as e:
 m=windows_memory();r={'status':'failed','type':type(e).__name__,'message':str(e)[:800],'elapsed_s':time.monotonic()-start,'free_ram':m['availableRamBytes'],'free_commit':m['commitLimitBytes']-m['committedBytes'],'traceback':[{'file':Path(v.filename).name,'line':v.lineno,'function':v.name} for v in traceback.extract_tb(e.__traceback__)]};(out/'failure.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);raise SystemExit(1)
