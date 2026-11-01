import os,sys,time,pathlib,json,hashlib,subprocess,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-incremental-fixed-calibration-20261101'); base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');G=1024**3
source=[base/'database.db',base/'prepared/reconstruction-input.json',base/'verification.json',base/'geometry-0.json']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 start=time.monotonic();before={str(p):sha(p) for p in source};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None
 if min(initial)>=6.5*G:
  with sqlite3.connect('file:'+str(base/'database.db')+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
  with sqlite3.connect(root/'database.db') as c:
   images=c.execute('select count(*) from images').fetchone()[0];pairs=c.execute('select count(*) from two_view_geometries where rows>0').fetchone()[0]
  assert images==166 and pairs==807,(images,pairs)
  import struct
  with sqlite3.connect(root/'database.db') as c:c.execute('update cameras set params=?,prior_focal_length=1', (struct.pack('<3d',604.171514438519,960.,540.),))
  (root/'snapshot').mkdir(exist_ok=True);(root/'models').mkdir(exist_ok=True)
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())
  t=time.monotonic()
  with (root/'map.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'map'],stdout=log,stderr=subprocess.STDOUT,env=env)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>180:
     reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.5)
   code=p.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in source};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'input_hashes_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((s[0] for s in samples),default=None),'min_commit':min((s[1] for s in samples),default=None),'exit':code,'stop':reason,'wall_seconds':time.monotonic()-start,'only_owned_child_terminated':True};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import pycolmap as p
o=p.IncrementalPipelineOptions(num_threads=4,random_seed=17,max_runtime_seconds=165,max_num_models=4,ignore_watermarks=True,structure_less_registration_fallback=False,ba_refine_sensor_from_rig=False,ba_refine_focal_length=False,ba_refine_principal_point=False,ba_refine_extra_params=False,ba_global_frames_ratio=2.,ba_global_points_ratio=2.,ba_local_max_num_iterations=10,ba_global_max_num_iterations=20,snapshot_path=str((root/'snapshot').resolve()),snapshot_frames_freq=10)
o.mapper.num_threads=4;o.mapper.abs_pose_refine_focal_length=False;o.mapper.abs_pose_refine_extra_params=False
(root/'options.txt').write_text(str(o)+'\nInitialization: automatic COLMAP; no custom seed. Input: 166 images, 807 nonempty verified pairs, one shared SIMPLE_PINHOLE fixed f=604.171514438519. Mapping deadline 180s, internal graceful stop at 165s; snapshot frequency 10 registered frames. Comparison changes mapper/threads/BA limits, not single-factor.\n')
models=p.incremental_mapping(root/'database.db',base/'prepared/images',root/'models',options=o)
from scripts.pilot.reconstruct_route import model_assessment
reports=[]
for identity,rec in models.items():
 if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
 geom,report=model_assessment(rec,base/'prepared',166,0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
(root/'report.json').write_text(json.dumps({'models':reports,'camera':'shared SIMPLE_PINHOLE f604.171514438519 fixed','no_autoaccept':True,'physical_calibration_verified':False},indent=2));print('components',len(models),flush=True)

