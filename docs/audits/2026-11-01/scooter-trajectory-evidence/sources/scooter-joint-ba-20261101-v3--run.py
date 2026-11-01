import os,sys,time,pathlib,subprocess,json,hashlib
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-joint-ba-20261101-v3');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');G=1024**3;source=[base/'geometry-0.json',base/'report.json']+sorted((base/'models/0').glob('*.bin'))+[pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json')]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in source};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];start=time.monotonic();runs=[];reason=None
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())+os.pathsep+str(pathlib.Path('.local-pilot/route-fusion-runtime').resolve())
  for name,limit in [('prepare',30),('w0',60),('w05',60),('w2',60)]:
   t=time.monotonic();reason=None
   if t-start>=180:runs.append({'stage':name,'stop':'total_timeout_before_start'});break
   with (root/(name+'.log')).open('w') as log:
    p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),name],stdout=log,stderr=subprocess.STDOUT,env=env)
    while p.poll() is None:
     m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
     if min(v)<4.5*G or time.monotonic()-start>180 or time.monotonic()-t>limit:
      reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
     time.sleep(.4)
    code=p.returncode
   runs.append({'stage':name,'exit':code,'stop':reason,'seconds':time.monotonic()-t});(root/'progress.json').write_text(json.dumps(runs,indent=2));print(runs[-1],flush=True)
   if name=='prepare' and (code!=0 or reason):break
   if reason=='memory_guard':break
 else:reason='admission_memory'
 after={str(p):sha(p) for p in source};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'initial_ram':initial[0],'initial_commit':initial[1],'stages':runs,'admission_stop':reason if not runs else None,'seconds':time.monotonic()-start,'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'input_hashes_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,pycolmap as p
from scipy.optimize import least_squares
from scipy.sparse import coo_matrix
from scripts.pilot.route_motion_audit import audit
stage=sys.argv[1];geom=json.loads((base/'geometry-0.json').read_text())
if stage=='prepare':
 rec=p.Reconstruction(base/'models/0');images=sorted(rec.images.values(),key=lambda im:im.name);assert len(images)==166 and len(geom['cameras'])==166 and all(im.name==g['image'] for im,g in zip(images,geom['cameras']));imidx={im.image_id:i for i,im in enumerate(images)};ticks=np.array([g['ticks_90k'] for g in geom['cameras']],np.int64);assert np.all(np.diff(ticks)>0);centers=np.array([im.cam_from_world().inverse().translation for im in images]);R=np.array([im.cam_from_world().rotation.matrix() for im in images]);K=np.array([rec.cameras[im.camera_id].calibration_matrix() for im in images]);ids=[];points=[];candidates=[[] for _ in range(8)]
 for pid,pt in rec.points3D.items():
  elements=list(pt.track.elements);train=[];hold=[]
  for e in elements:
   if e.image_id not in imidx:continue
   token=f'{e.image_id}:{pid}'.encode();v=int.from_bytes(hashlib.blake2b(token,digest_size=8).digest(),'little')%5
   (hold if v==0 else train).append((imidx[e.image_id],e.point2D_idx))
  if len(train)<3 or not hold:continue
  i=int(np.median([x[0] for x in train]));bucket=min(7,8*i//len(images));rank=hashlib.blake2b(f'point:{pid}'.encode(),digest_size=8).digest();candidates[bucket].append((rank,pid,train,hold))
 for group in candidates:group.sort(key=lambda x:x[0])
 chosen=[]
 while len(chosen)<2000 and any(candidates):
  for group in candidates:
   if group and len(chosen)<2000:chosen.append(group.pop(0))
 if not chosen:raise RuntimeError('no_eligible_points')
 ci=[];pi=[];uv=[];ishold=[];ids=[];xyz=[]
 for j,(_,pid,train,hold) in enumerate(chosen):
  pt=rec.points3D[pid];ids.append(pid);xyz.append(pt.xyz)
  for test,track in [(False,train),(True,hold)]:
   for cam,idx in track:ci.append(cam);pi.append(j);uv.append(images[cam].point2D(idx).xy);ishold.append(test)
 ci=np.asarray(ci,np.int32);pi=np.asarray(pi,np.int32);uv=np.asarray(uv,float);ishold=np.asarray(ishold,bool);xyz=np.asarray(xyz,float);dt=np.diff(ticks)/90000;rates=np.linalg.norm(np.diff(centers,axis=0),axis=1)/dt;norm=float(np.median(rates));anchor=int(np.argmin(abs(ticks/90000-12.)));L=float(np.linalg.norm(centers[anchor]-centers[0]));assert norm>0 and L>1e-9
 np.savez_compressed(root/'data.npz',centers=centers,R=R,K=K,ticks=ticks,xyz=xyz,ci=ci,pi=pi,uv=uv,hold=ishold,point_ids=np.array(ids),anchor=np.array(anchor),anchor_distance=np.array(L),velocity_norm=np.array(norm));r={'points':len(ids),'cameras':len(images),'observations':len(ci),'train_obs':int((~ishold).sum()),'heldout_obs':int(ishold.sum()),'hash_split':'blake2b-64(image_id:point_id) mod 5==0 heldout; retained points >=3 training + >=1 heldout','temporal_stratification':'8 bins of median training camera index, deterministic point-hash rank, round-robin','anchor_frame':images[anchor].name,'anchor_seconds':float(ticks[anchor]/90000),'anchor_distance':L,'velocity_norm_baseline_median':norm,'holdout_limit':'2D observations held out only from this fitting; baseline cameras/points were built using all views'};(root/'prepare.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
weight={'w0':0.,'w05':.5,'w2':2.}[stage];dest=root/stage;dest.mkdir();z=np.load(root/'data.npz');C0=z['centers'];R=z['R'];K=z['K'];ticks=z['ticks'];P0=z['xyz'];ci=z['ci'];pi=z['pi'];uv=z['uv'];hold=z['hold'];anchor=int(z['anchor']);L=float(z['anchor_distance']);norm=float(z['velocity_norm']);dt=np.diff(ticks)/90000;n=len(C0);pointbase=[];xlist=[]
for i in range(1,n):
 pointbase.append(len(xlist));d=C0[i]-C0[0]
 if i==anchor:
  unit=d/L;xlist.extend([np.arctan2(unit[1],unit[0]),np.arctan2(unit[2],np.hypot(unit[0],unit[1]))])
 else:xlist.extend(C0[i].tolist())
cp=len(xlist);starts=[None]+pointbase;x0=np.r_[xlist,P0.ravel()]
def unpack(x):
 c=np.empty_like(C0);c[0]=C0[0]
 for i in range(1,n):
  j=starts[i]
  if i==anchor:
   th,ph=x[j:j+2];c[i]=C0[0]+L*np.array([np.cos(ph)*np.cos(th),np.cos(ph)*np.sin(th),np.sin(ph)])
  else:c[i]=x[j:j+3]
 return c,x[cp:].reshape(-1,3)
def pixels(c,p,which):
 cc=ci[which];pp=pi[which];q=np.einsum('nij,nj->ni',R[cc],p[pp]-c[cc]);depth=q[:,2];safe=np.where(abs(depth)<1e-7,np.where(depth<0,-1e-7,1e-7),depth);proj=np.column_stack([K[cc,0,0]*q[:,0]/safe+K[cc,0,2],K[cc,1,1]*q[:,1]/safe+K[cc,1,2]]);return proj-uv[which],depth
train=np.flatnonzero(~hold);test=np.flatnonzero(hold);calls=0;start=time.monotonic()
def residual(x):
 global calls
 calls+=1
 if calls%8==0:
  m=windows_memory()
  if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*G:raise RuntimeError('memory_guard')
 c,p=unpack(x);r,_=pixels(c,p,train);v=np.diff(c,axis=0)/dt[:,None];return np.r_[r.ravel(),(weight*np.diff(v,axis=0)/norm).ravel()]
# Sparse finite-difference structure for image residuals and second-difference velocity prior.
rr=[];cc=[]
def add(rows,cols):
 for row in rows:
  for col in cols:rr.append(row);cc.append(col)
for q,idx in enumerate(train):
 cam=int(ci[idx]);pt=int(pi[idx]);cols=list(range(cp+3*pt,cp+3*pt+3))
 if cam:cols+=list(range(starts[cam],starts[cam]+(2 if cam==anchor else 3)))
 add([2*q,2*q+1],cols)
offset=2*len(train)
for j in range(n-2):
 cols=[]
 for cam in (j,j+1,j+2):
  if cam:cols+=list(range(starts[cam],starts[cam]+(2 if cam==anchor else 3)))
 add(range(offset+3*j,offset+3*j+3),cols)
J=coo_matrix((np.ones(len(rr),np.int8),(rr,cc)),shape=(offset+3*(n-2),len(x0))).tocsr()
print('starting',stage,'train',len(train),'heldout',len(test),'variables',len(x0),'jac_nnz',J.nnz,flush=True)
res=least_squares(residual,x0,jac_sparsity=J,method='trf',tr_solver='lsmr',loss='soft_l1',f_scale=2.,x_scale='jac',max_nfev=500,ftol=1e-6,xtol=1e-6,gtol=1e-6,tr_options={'maxiter':40});C,P=unpack(res.x)
def score(c,p,ix):
 residuals,depth=pixels(c,p,ix);e=np.linalg.norm(residuals,axis=1);return {'observations':len(e),'median_px':float(np.median(e)),'p95_px':float(np.percentile(e,95)),'behind':int((depth<=0).sum())}
for row,c in zip(geom['cameras'],C):
 row['center']=c.tolist()
 for j in range(3):row['camera_to_world'][j][3]=float(c[j])
geom['points']=[[*P[i].tolist(),0,0,0] for i in range(len(P))];geom.update(camera_path_units=float(np.linalg.norm(np.diff(C,axis=0),axis=1).sum()),execution_qualified=False,navigation_qualified=False,diagnostic_partial_point_subset=True)
(dest/'geometry.json').write_text(json.dumps(geom));np.savez_compressed(dest/'fit.npz',centers=C,points=P)
report={'weight':weight,'points':len(P),'cameras':len(C),'before_train':score(C0,P0,train),'after_train':score(C,P,train),'before_heldout':score(C0,P0,test),'after_heldout':score(C,P,test),'anchor_distance_before':L,'anchor_distance_after':float(np.linalg.norm(C[anchor]-C[0])),'rotation_and_intrinsics_fixed':True,'prior':'weight * ((C[i+1]-C[i])/dt[i] - (C[i]-C[i-1])/dt[i-1]) / baseline_median_camera_rate','gauge':'first camera fixed; anchor camera distance from first fixed exactly, direction free','loss':'soft_l1 over 2D reprojection and prior, f_scale=2px','nfev':res.nfev,'status':res.status,'message':res.message,'cost':res.cost,'optimality':res.optimality,'elapsed_s':time.monotonic()-start,'function_calls':calls,'converged':res.status>0,'accepted':False,'warning':'Baseline poses and points used all observations before this split; held-out observations excluded only from this fitting; not independent capture.'}
(dest/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
