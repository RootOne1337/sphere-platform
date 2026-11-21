import os,sys,json,sqlite3
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
sys.path.insert(0,str(Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
import pycolmap as p
cv2.setNumThreads(2)
out=Path('.local-pilot/scooter-jump-forensics-20261101');root=Path('.local-pilot/scooter-stage-global-focal-20261101');imgs=Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared/images');data=json.loads((out/'report.json').read_text());cams={c['image']:c for c in json.loads((root/'geometry-0.json').read_text())['cameras']};f,cx,cy=data['camera_intrinsics'];K=np.array([[f,0,cx],[0,f,cy],[0,0,1.]]);rec=p.Reconstruction(root/'models/0');models={im.name:im for im in rec.images.values()}
rows=[]
with sqlite3.connect((root/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 ids={name:i for i,name in db.execute('select image_id,name from images')};kps={i:np.frombuffer(blob,dtype='<f4').reshape(n,c)[:,:2].copy() for i,n,c,blob in db.execute('select image_id,rows,cols,data from keypoints')}
 for r in data['pairs']:
  a,b=r['first'],r['second'];ia,ib=ids[a],ids[b];pid=min(ia,ib)*2147483647+max(ia,ib);n,col,blob=db.execute('select rows,cols,data from two_view_geometries where pair_id=?',(pid,)).fetchone();m=np.frombuffer(blob,dtype='<u4').reshape(n,col)
  if ia>ib:m=m[:,::-1]
  p0=kps[ia][m[:,0]];p1=kps[ib][m[:,1]];disp=p1-p0;mag=np.linalg.norm(disp,axis=1)
  R1=np.asarray(cams[a]['camera_to_world'])[:,:3];R2=np.asarray(cams[b]['camera_to_world'])[:,:3];R21=R2.T@R1
  h=(K@R21@np.linalg.inv(K)@np.c_[p0,np.ones(len(p0))].T).T;valid=h[:,2]>0;pred=h[valid,:2]/h[valid,2,None];res=np.linalg.norm(pred-p1[valid],axis=1);angle=np.degrees(np.arccos(np.clip((np.trace(R21)-1)/2,-1,1)))
  cv2.setRNGSeed(17);E,inliers=cv2.findEssentialMat(p0,p1,K,method=cv2.RANSAC,prob=.999,threshold=2.,maxIters=2000);direct=None
  if E is not None and E.shape==(3,3):
   count,rd,td,pm=cv2.recoverPose(E,p0,p1,K,mask=inliers.copy());direct={'ransac_inliers':int(inliers.sum()),'positive_depth':int(count),'rotation_degrees':float(np.degrees(np.arccos(np.clip((np.trace(rd)-1)/2,-1,1)))),'rotation_disagreement_with_global_deg':float(np.degrees(np.arccos(np.clip((np.trace(rd@R21.T)-1)/2,-1,1))))}
  ca=np.asarray(cams[a]['center']);cb=np.asarray(cams[b]['center']);angles=[]
  for u,v in m:
   x=models[a].point2D(int(u));y=models[b].point2D(int(v))
   if x.has_point3D() and y.has_point3D() and x.point3D_id==y.point3D_id:
    xyz=rec.points3D[x.point3D_id].xyz;ra=xyz-ca;rb=xyz-cb;cos=np.dot(ra,rb)/(np.linalg.norm(ra)*np.linalg.norm(rb));angles.append(float(np.degrees(np.arccos(np.clip(abs(cos),-1,1)))))
  rows.append({'pair':[a,b],'count':n,'rotation_degrees':float(angle),'direct_essential_assumed_focal':direct,'shared_3d_pair_angle_deg':{'count':len(angles),'median':float(np.median(angles)) if angles else None,'below_1_deg':sum(v<1 for v in angles),'below_2_deg':sum(v<2 for v in angles)},'median_image_displacement_xy_px':np.median(disp,axis=0).tolist(),'median_image_displacement_magnitude_px':float(np.median(mag)),'p90_image_displacement_magnitude_px':float(np.percentile(mag,90)),'image_displacement_over_100px':int((mag>100).sum()),'image_displacement_over_200px':int((mag>200).sum()),'source_y_quartile_counts':[int(((p0[:,1]>=270*j)&(p0[:,1]<270*(j+1))).sum()) for j in range(4)],'pure_rotation_prediction_residual_px_median':float(np.median(res)),'pure_rotation_prediction_residual_px_p90':float(np.percentile(res,90)),'pure_rotation_prediction_valid':int(valid.sum())})
examples=data['pairs'][1]['lk_examples_high_disagreement'][:3];before=cv2.imread(str(imgs/data['pairs'][1]['first']));after=cv2.imread(str(imgs/data['pairs'][1]['second']))
def crop(image,xy):
 x,y=np.rint(xy).astype(int);pad=cv2.copyMakeBorder(image,100,100,140,140,cv2.BORDER_CONSTANT,value=(0,0,0));z=pad[y:y+200,x:x+280].copy();cv2.drawMarker(z,(140,100),(0,255,255),cv2.MARKER_CROSS,15,1);return z
panels=[]
for x in examples:
 a=crop(before,np.array(x['source_xy_colmap'])-.5);b=crop(after,np.array(x['target_xy_colmap'])-.5);c=crop(after,x['lk_target_xy_image']);
 for im,label in [(a,'source'),(b,'verified match'),(c,'LK candidate')]:cv2.putText(im,label,(4,15),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1,cv2.LINE_AA)
 panels.append(np.concatenate([a,b,c],axis=1))
cv2.imwrite(str(out/'disagreement-crops.jpg'),np.concatenate(panels,axis=0),[cv2.IMWRITE_JPEG_QUALITY,93]);result={'pairs':rows,'caveat':'2D displacement and rotation-only residual use saved model relative rotation and fitted f603.24; true intrinsics and depth unknown. LK examples are ambiguities, not proven mismatches. Absolute coordinates in separate report.'};(out/'flow-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result,indent=2))
