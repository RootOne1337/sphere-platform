import os,sys,json,pathlib,hashlib
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()));sys.path.insert(0,str(pathlib.Path('.local-pilot/route-fusion-runtime').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import numpy as np,pycolmap as p
from scipy.spatial.transform import Rotation
base=pathlib.Path('.local-pilot/scooter-incremental-bounded-20261101');root=pathlib.Path('.local-pilot/scooter-incremental-merge-20261101');m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*1024**3
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
files=sorted((base/'models/1').glob('*.bin'))+sorted((base/'models/2').glob('*.bin'))+[base/'database.db'];before={str(x):sha(x) for x in files};a=p.Reconstruction(base/'models/1');b=p.Reconstruction(base/'models/2');A={im.name:im for im in a.images.values() if im.has_pose};B={im.name:im for im in b.images.values() if im.has_pose};names=sorted(A.keys()&B.keys());assert len(names)==20
ca=np.array([A[n].cam_from_world().inverse().translation for n in names]);cb=np.array([B[n].cam_from_world().inverse().translation for n in names]);rots=Rotation.from_matrix(np.array([B[n].cam_from_world().rotation.matrix().T @ A[n].cam_from_world().rotation.matrix() for n in names]));r=rots[:10].mean()
for _ in range(50):
 tangent=(r.inv()*rots[:10]).as_rotvec();n=np.maximum(np.linalg.norm(tangent,axis=1),1e-8);step=np.average(tangent,axis=0,weights=1/n);r=r*Rotation.from_rotvec(step)
 if np.linalg.norm(step)<1e-10:break
Q=r.as_matrix();x=(Q@ca.T).T;y=cb;xc=x[:10]-x[:10].mean(0);yc=y[:10]-y[:10].mean(0);rawscale=float(np.sum(xc*yc)/np.sum(xc*xc));scale=max(rawscale,0.);translation=y[:10].mean(0)-scale*x[:10].mean(0);centerr=np.linalg.norm(scale*x+translation-y,axis=1);rotations=np.degrees((r.inv()*rots).magnitude());step=float(np.median(np.linalg.norm(np.diff(cb,axis=0),axis=1)));pxtrain=[];pxtest=[];behind=[0,0];counts=[0,0]
for k,name in enumerate(names):
 ia=A[name];ib=B[name];cam=b.cameras[ib.camera_id];R=ib.cam_from_world().rotation.matrix();t=ib.cam_from_world().translation;f,cx,cy=cam.params;bucket=0 if k<10 else 1
 for j in range(ia.num_points2D()):
  pa=ia.point2D(j);pb=ib.point2D(j)
  if not pa.has_point3D() or not pb.has_point3D():continue
  point=a.points3D[pa.point3D_id].xyz;trans=scale*Q@point+translation;q=R@trans+t;counts[bucket]+=1
  if q[2]<=0:behind[bucket]+=1;continue
  proj=np.array([f*q[0]/q[2]+cx,f*q[1]/q[2]+cy]);(pxtrain if bucket==0 else pxtest).append(float(np.linalg.norm(proj-pb.xy)))
def summary(v):
 v=np.asarray(v);return {'count':int(len(v)),'median':float(np.median(v)),'p95':float(np.percentile(v,95))}
after={str(x):sha(x) for x in files};result={'method':'orientation geodesic median from first 10; positive scale plus translation least-squares on first 10 centers; last 10 camera views held out by time','names_train':names[:10],'names_test':names[10:],'rotation_align':Q.tolist(),'unconstrained_scale':rawscale,'scale':scale,'translation':translation.tolist(),'median_target_camera_step':step,'rotation_degrees_train':summary(rotations[:10]),'rotation_degrees_test':summary(rotations[10:]),'center_units_train':summary(centerr[:10]),'center_units_test':summary(centerr[10:]),'center_relative_to_target_median_step_train':summary(centerr[:10]/step),'center_relative_to_target_median_step_test':summary(centerr[10:]/step),'cross_projection_error_px_train':summary(pxtrain),'cross_projection_error_px_test':summary(pxtest),'both_triangulated_count_train_test':counts,'behind_target_camera_train_test':behind,'camera_focal_component_1':float(next(iter(a.cameras.values())).params[0]),'camera_focal_component_2':float(next(iter(b.cameras.values())).params[0]),'input_hashes_unchanged':before==after,'interpretation':'Same source observations used in construction of both models: heldout only from alignment fit, not independent capture. Cross-projection uses component-2 intrinsics and component-1 3D points. No merge or acceptance.'};(root/'orientation-check.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('names')},indent=2))
