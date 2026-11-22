import os,sys,time,pathlib,json,hashlib,subprocess,sqlite3,ctypes
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-disk-cpu-20261101'); inp=pathlib.Path('.local-pilot/scooter-disk-lg-20261101-v3');prep=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2/prepared');G=1024**3
sources=[inp/'features.db',inp/'cpu-input.db',inp/'pairs.txt',inp/'result.json',prep/'reconstruction-input.json']
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 start=time.monotonic();before={str(x):sha(x) for x in sources};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None
 if min(initial)>=4.5*G:
  with sqlite3.connect('file:'+str(inp/'cpu-input.db')+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
  with sqlite3.connect(root/'database.db') as c:
   counts={tab:c.execute('select count(*) from '+tab).fetchone()[0] for tab in ('images','cameras','keypoints','descriptors','matches','two_view_geometries')}
  assert counts=={'images':166,'cameras':1,'keypoints':166,'descriptors':0,'matches':811,'two_view_geometries':0},counts
  (root/'models').mkdir(exist_ok=True);env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve());t=time.monotonic()
  with (root/'map.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'map'],stdout=log,stderr=subprocess.STDOUT,env=env)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-start>120:
     reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.4)
   code=p.returncode
 else:reason='admission_memory'
 after={str(x):sha(x) for x in sources};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'input_hashes_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'exit':code,'stop':reason,'wall_seconds':time.monotonic()-start,'gpu_released_before_start':True,'only_owned_child_terminated':True};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import pycolmap as p
dbpath=root/'database.db';opts=p.TwoViewGeometryOptions();opts.ransac.num_threads=1;opts.filter_stationary_matches=False;(root/'options.txt').write_text('DISK+LG 640x360, coordinates mapped to 1920x1080. 4 CPU affinity, RANSAC 1 thread per pair (COLMAP requires it), stationary filtering false, global shared SIMPLE_PINHOLE initial f604.4325003117685, focal refined, max 30 BA iterations, max tracks 30000, random seed 17; total 120s and reserve 4.5GiB. Different method/resolution from SIFT; no independent pose holdout.\n'+str(opts));p.verify_matches(dbpath,inp/'pairs.txt',options=opts)
with sqlite3.connect(dbpath) as c:counts={'raw':c.execute('select count(*) from matches').fetchone()[0],'verified_nonempty':c.execute('select count(*) from two_view_geometries where rows>0').fetchone()[0],'all_verification_records':c.execute('select count(*) from two_view_geometries').fetchone()[0]}
(root/'verification.json').write_text(json.dumps(counts,indent=2));print('verified',counts,flush=True)
with p.Database.open(dbpath) as db:
 cams=db.read_all_cameras();assert len(cams)==1;cam=cams[0];cam.params=[604.4325003117685,960.,540.];cam.has_prior_focal_length=True;db.update_camera(cam)
assert p.calibrate_view_graph(dbpath,p.ViewGraphCalibrationOptions(random_seed=17))
o=p.GlobalPipelineOptions(num_threads=4,random_seed=17,ignore_watermarks=True);o.mapper.num_threads=4;o.mapper.refine_sensor_from_rig=False;o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False;o.mapper.rotation_averaging.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_focal_length=True;o.mapper.bundle_adjustment.refine_extra_params=False;o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=4;o.mapper.bundle_adjustment.ceres.solver_options.max_num_iterations=30;o.mapper.keep_max_num_tracks=30000
with (root/'options.txt').open('a') as f:f.write('\n'+str(o))
models=p.global_mapping(dbpath,prep/'images',root/'models',options=o)
from scripts.pilot.reconstruct_route import model_assessment
reports=[]
for identity,rec in models.items():
 if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
 geom,report=model_assessment(rec,prep,166,0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
(root/'report.json').write_text(json.dumps({'models':reports,'camera':'shared SIMPLE_PINHOLE f604.4325 initial refined','no_autoaccept':True,'physical_calibration_verified':False,'independent_pose_holdout':False},indent=2));print('components',len(models),flush=True)
