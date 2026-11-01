import os,sys,time,json,pathlib,subprocess,hashlib,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-stage-verify-map-20261101');stage=pathlib.Path('.local-pilot/scooter-stage-isolation-20261101');src=stage/'database.db';pairs=stage/'learned-pairs.txt';receipt=stage/'stage2-receipt.json';prepared=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared');G=1024**3
inputs=[src,pairs,receipt,prepared/'reconstruction-input.json',pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input/video.h264')]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in inputs};r=json.loads(receipt.read_text());assert r['status']=='matching_complete_not_verified' and r['raw_pairs']==796 and before[str(src)]==r['database_sha256'] and before[str(pairs)]==r['pair_file_sha256'];(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];start=time.monotonic();reason=None;code=None
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
 after={str(p):sha(p) for p in inputs};(root/'hash-after.json').write_text(json.dumps(after,indent=2));out={'exit':code,'stop':reason,'seconds':time.monotonic()-start,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'source_hashes_match_stage2_receipt':True,'input_hashes_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(out,indent=2));print(json.dumps(out));sys.exit()
import ctypes
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();process_mask=ctypes.c_size_t();system_mask=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(process_mask),ctypes.byref(system_mask));bits=[1<<i for i in range(64) if process_mask.value & (1<<i)];assert len(bits)>=2;chosen=bits[0]|bits[1];assert k.SetProcessAffinityMask(proc,ctypes.c_size_t(chosen));print('two logical processors affinity',chosen,flush=True)
with sqlite3.connect(src.resolve().as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
import pycolmap as p
v=p.TwoViewGeometryOptions();v.ransac.num_threads=1;v.filter_stationary_matches=False;p.verify_matches(root/'database.db',pairs,options=v)
with sqlite3.connect(root/'database.db') as c:
 counts={'raw_pairs':c.execute('select count(*) from matches').fetchone()[0],'verified_pairs_total':c.execute('select count(*) from two_view_geometries').fetchone()[0],'verified_pairs_nonempty':c.execute('select count(*) from two_view_geometries where rows>0').fetchone()[0]}
(root/'verification.json').write_text(json.dumps(counts,indent=2));print('verified',counts,flush=True)
modelsdir=root/'models';modelsdir.mkdir();opts=p.IncrementalPipelineOptions(num_threads=2,random_seed=17,max_runtime_seconds=100,max_num_models=4,ignore_watermarks=True,structure_less_registration_fallback=False,ba_refine_sensor_from_rig=False);opts.mapper.num_threads=2
models=p.incremental_mapping(root/'database.db',prepared/'images',modelsdir,options=opts)
from scripts.pilot.reconstruct_route import model_assessment
reports=[]
for identity,rec in models.items():
 if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
 geom,report=model_assessment(rec,prepared,163,0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
(root/'report.json').write_text(json.dumps({'models':reports,'selected_views':163,'camera_model':'SIMPLE_PINHOLE optimized focal','no_autoaccept':True,'physical_calibration_verified':False,'source_stage2_db_immutable':True},indent=2));print('completed',len(models),'models',flush=True)
