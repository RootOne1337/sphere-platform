import os,sys,time,json,pathlib,subprocess,hashlib,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-stage-global-20261101');source=pathlib.Path('.local-pilot/scooter-stage-verify-map-20261101');db=source/'database.db';prepared=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared');video=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input/video.h264');inputs=[db,source/'verification.json',source/'receipt.json',prepared/'reconstruction-input.json',video];G=1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in inputs};v=json.loads((source/'verification.json').read_text());assert v['raw_pairs']==796 and v['verified_pairs_nonempty']==783;(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];start=time.monotonic();reason=None;code=None
 if min(initial)<4.5*G:reason='admission_memory'
 else:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())
  with (root/'worker.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'worker'],stdout=log,stderr=subprocess.STDOUT,env=env)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-start>120:reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.5)
   code=p.returncode
 after={str(p):sha(p) for p in inputs};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'exit':code,'stop':reason,'seconds':time.monotonic()-start,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'source_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));sys.exit()
import ctypes
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=2 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(bits[0]|bits[1]));print('affinity two logical CPUs',flush=True)
with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
import pycolmap as p
with p.Database.open(root/'database.db') as database:
 for cam in database.read_all_cameras():
  assert (cam.width,cam.height)==(1920,1080);cam.params=[960.,960.,540.];cam.has_prior_focal_length=True;database.update_camera(cam)
assert p.calibrate_view_graph(root/'database.db',p.ViewGraphCalibrationOptions(random_seed=17))
o=p.GlobalPipelineOptions(num_threads=2,random_seed=17,ignore_watermarks=True);o.mapper.num_threads=2;o.mapper.refine_sensor_from_rig=False;o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False;o.mapper.rotation_averaging.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_focal_length=False;o.mapper.bundle_adjustment.refine_extra_params=False;o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=2;o.mapper.bundle_adjustment.ceres.solver_options.max_num_iterations=30;o.mapper.keep_max_num_tracks=30000
modelsdir=root/'models';modelsdir.mkdir();models=p.global_mapping(root/'database.db',prepared/'images',modelsdir,options=o)
from scripts.pilot.reconstruct_route import model_assessment
reports=[]
for identity,rec in models.items():
 if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
 geom,report=model_assessment(rec,prepared,163,0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
(root/'report.json').write_text(json.dumps({'models':reports,'camera':'fixed f960 SIMPLE_PINHOLE','physical_calibration_verified':False,'no_autoaccept':True},indent=2));print('components',len(models),flush=True)
