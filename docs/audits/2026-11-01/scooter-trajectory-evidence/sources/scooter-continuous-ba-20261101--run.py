import os,sys,time,pathlib,json,hashlib,subprocess
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-continuous-ba-20261101'); old=pathlib.Path('.local-pilot/scooter-joint-ba-20261101-v3'); base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2'); G=1024**3
sources=[old/'data.npz',old/'w0/fit.npz',old/'w0/report.json',base/'geometry-0.json',pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json'),pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json')]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in sources};(root/'hash-before.json').write_text(json.dumps(before,indent=2)); start=time.monotonic();samples=[];runs=[];m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']]
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/route-fusion-runtime').resolve())
  for stage in ('0.5','1.0'):
   t=time.monotonic();reason=None
   with (root/('spline-'+stage+'.log')).open('w') as log:
    p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),stage],stdout=log,stderr=subprocess.STDOUT,env=env)
    while p.poll() is None:
     m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
     if min(v)<4.5*G or time.monotonic()-t>120 or time.monotonic()-start>240:
      reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
     time.sleep(.4)
   runs.append({'stage':stage,'exit':p.returncode,'stop':reason,'seconds':time.monotonic()-t});(root/'progress.json').write_text(json.dumps(runs,indent=2));print(runs[-1],flush=True)
   if reason=='memory_guard' or time.monotonic()-start>=240:break
 after={str(p):sha(p) for p in sources};(root/'hash-after.json').write_text(json.dumps(after,indent=2));receipt={'initial_ram':initial[0],'initial_commit':initial[1],'runs':runs,'admission_stop':None if runs else 'memory_guard','seconds':time.monotonic()-start,'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'inputs_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True);sys.exit()
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import least_squares
from scipy.sparse import coo_matrix
spacing=float(sys.argv[1]);dest=root/('spline-'+sys.argv[1]);dest.mkdir(exist_ok=True)
z=np.load(old/'data.npz');C0=z['centers'];R=z['R'];K=z['K'];ticks=z['ticks'];P0=z['xyz'];ci=z['ci'];pi=z['pi'];uv=z['uv'];hold=z['hold'];anchor=int(z['anchor']);L=float(z['anchor_distance']);t=(ticks-ticks[0])/90000.;end=t[-1];internal=np.arange(spacing,end,spacing);knots=np.r_[[0.]*4,internal,[end]*4]; B=BSpline.design_matrix(t,knots,3).toarray(); nk=B.shape[1]; Q=np.linalg.lstsq(B,C0,rcond=None)[0];Q[0]=C0[0];j=int(np.argmax(B[anchor]));assert j not in (0,) and B[anchor,j]>1e-9
v=C0[anchor]-C0[0];theta=np.arctan2(v[1],v[0]);phi=np.arctan2(v[2],np.hypot(v[0],v[1]));free=[i for i in range(1,nk) if i!=j];starts={k:2+3*i for i,k in enumerate(free)};cp=2+3*len(free);x0=np.r_[[theta,phi],Q[free].ravel(),P0.ravel()];train=np.flatnonzero(~hold);test=np.flatnonzero(hold)
def unpack(x):
 q=np.empty((nk,3));q[0]=C0[0];q[free]=x[2:cp].reshape(-1,3);th,ph=x[:2];target=C0[0]+L*np.array([np.cos(ph)*np.cos(th),np.cos(ph)*np.sin(th),np.sin(ph)]);q[j]=(target-B[anchor,:]@np.nan_to_num(np.vstack([q[:j],np.zeros((1,3)),q[j+1:]])))/B[anchor,j];return B@q,x[cp:].reshape(-1,3)
def pixels(c,p,which):
 cc=ci[which];pp=pi[which];q=np.einsum('nij,nj->ni',R[cc],p[pp]-c[cc]);d=q[:,2];safe=np.where(abs(d)<1e-7,np.where(d<0,-1e-7,1e-7),d);proj=np.column_stack([K[cc,0,0]*q[:,0]/safe+K[cc,0,2],K[cc,1,1]*q[:,1]/safe+K[cc,1,2]]);return proj-uv[which],d
calls=0
def residual(x):
 global calls
 calls+=1
 if calls%8==0:
  m=windows_memory()
  if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*G:raise RuntimeError('memory_guard')
 c,p=unpack(x);return pixels(c,p,train)[0].ravel()
rr=[];cols=[];anchorknots=np.flatnonzero(B[anchor])
for obs,idx in enumerate(train):
 cam=int(ci[idx]);pt=int(pi[idx]);ks=set(np.flatnonzero(B[cam]));extra=[]
 if j in ks:ks.update(anchorknots);extra=[0,1]
 cs=extra+[col for k in ks if k in starts for col in range(starts[k],starts[k]+3)]+list(range(cp+3*pt,cp+3*pt+3))
 for row in (2*obs,2*obs+1):rr.extend([row]*len(cs));cols.extend(cs)
J=coo_matrix((np.ones(len(rr),np.int8),(rr,cols)),shape=(2*len(train),len(x0))).tocsr();start=time.monotonic();print('start',spacing,'knots',nk,'train',len(train),'heldout',len(test),'jac',J.nnz,flush=True)
res=least_squares(residual,x0,jac_sparsity=J,method='trf',tr_solver='lsmr',loss='soft_l1',f_scale=2.,x_scale='jac',max_nfev=500,ftol=1e-6,xtol=1e-6,gtol=1e-6,tr_options={'maxiter':40});C,P=unpack(res.x)
def score(c,p,ix):
 r,d=pixels(c,p,ix);e=np.linalg.norm(r,axis=1);return {'observations':len(e),'mean_px':float(np.mean(e)),'median_px':float(np.median(e)),'p95_px':float(np.percentile(e,95)),'behind':int((d<=0).sum())}
geom=json.loads((base/'geometry-0.json').read_text())
for row,c in zip(geom['cameras'],C):
 row['center']=c.tolist()
 for k in range(3):row['camera_to_world'][k][3]=float(c[k])
geom['points']=[[*P[i].tolist(),0,0,0] for i in range(len(P))];geom.update(camera_path_units=float(np.linalg.norm(np.diff(C,axis=0),axis=1).sum()),continuous_time_parameterization={'type':'cubic_bspline','uniform_knot_spacing_seconds':spacing,'actual_source_pts':True},poses_regularized=True,point_subset=2000,execution_qualified=False,navigation_qualified=False,diagnostic_partial_point_subset=True)
(dest/'geometry.json').write_text(json.dumps(geom));np.savez_compressed(dest/'fit.npz',centers=C,points=P)
w0=np.load(old/'w0/fit.npz');report={'spacing_seconds':spacing,'knots':nk,'points':len(P),'cameras':len(C),'initial_center_fit_rms':float(np.sqrt(np.mean((B@Q-C0)**2))),'baseline_w0_train':score(w0['centers'],w0['points'],train),'baseline_w0_heldout':score(w0['centers'],w0['points'],test),'train':score(C,P,train),'heldout':score(C,P,test),'anchor_distance_before':L,'anchor_distance_after':float(np.linalg.norm(C[anchor]-C[0])),'first_center_error':float(np.linalg.norm(C[0]-C0[0])),'rotation_and_intrinsics_fixed':True,'objective':'actual training 2D reprojection only, soft_l1 f_scale=2px; exact first-camera and anchor-radius gauge; no HUD or velocity prior','gauge_dependency':'eliminated anchor spline control depends on other controls active at anchor','nfev':res.nfev,'status':res.status,'message':res.message,'elapsed_s':time.monotonic()-start,'function_calls':calls,'converged':res.status>0,'accepted':False,'warning':'Baseline geometry used all observations before this split. Held out here only, not an independent capture; spline parameterization regularizes poses.'};(dest/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
