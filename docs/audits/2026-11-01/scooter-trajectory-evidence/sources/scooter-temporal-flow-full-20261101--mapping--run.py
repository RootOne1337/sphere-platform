"""Prepared handoff runner. Do not invoke before a verified completed handoff."""
import os,sys,time,pathlib,json,hashlib,subprocess,sqlite3,ctypes,threading
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-temporal-flow-full-20261101/mapping');prepared=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2/prepared');G=1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)>1 and sys.argv[1]=='run':
 if len(sys.argv)!=5:raise SystemExit('run HANDOFF_DATABASE PAIR_FILE HANDOFF_RECEIPT')
 db,pairs,receipt=map(pathlib.Path,sys.argv[2:]);assert all(x.is_file() and not x.is_symlink() for x in (db,pairs,receipt));source=[db,pairs,receipt,prepared/'reconstruction-input.json'];before={str(p):sha(p) for p in source};(root/'input-hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None;soft=False;start=time.monotonic()
 if min(initial)>=6*G:
  with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
  with sqlite3.connect(root/'database.db') as c:counts={t:c.execute('select count(*) from '+t).fetchone()[0] for t in ('images','cameras','keypoints','matches','two_view_geometries')}
  assert counts['images']==166 and counts['cameras']==1 and counts['keypoints']==166 and counts['two_view_geometries']==0 and counts['matches']>0,counts
  (root/'models').mkdir(exist_ok=True);env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve()),str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())]);t=time.monotonic()
  with (root/'worker.log').open('w') as log:
   proc=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker',str(pairs.resolve())],stdout=log,stderr=subprocess.STDOUT,env=env)
   (root/'worker-pid.json').write_text(json.dumps({'owned_pid':proc.pid,'executable':sys._base_executable}));
   while proc.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v);elapsed=time.monotonic()-t
    if elapsed>120 and not soft:soft=True;(root/'soft-deadline.json').write_text(json.dumps({'seconds':elapsed,'note':'global_mapping has no cancellation token; hard 150s process deadline remains'}))
    if min(v)<4.5*G or elapsed>150:reason='memory_guard' if min(v)<4.5*G else 'hard_timeout';proc.kill();proc.wait();break
    time.sleep(.4)
   code=proc.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in source};(root/'input-hash-after.json').write_text(json.dumps(after,indent=2));out={'input_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'exit':code,'stop':reason,'soft120_crossed':soft,'total_seconds_including_copy_hash':time.monotonic()-start,'owned_child_only':True};(root/'receipt.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True);sys.exit()
if len(sys.argv)>1 and sys.argv[1]=='worker':
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
 from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
 initialize_route_cpu_runtime()
 import pycolmap as p
 token=p.CancellationToken();softstop=threading.Timer(120.,token.cancel);softstop.daemon=True;softstop.start();start=time.monotonic();db=root/'database.db';opts=p.TwoViewGeometryOptions();opts.ransac.num_threads=1;opts.filter_stationary_matches=False
 (root/'options.txt').write_text('CPU affinity4; verify RANSAC1 per pair; global native rotations, SIMPLE_PINHOLE f604.17 initial/shared/refined, global BA max30/4threads maxtracks30000; 120s soft / 150s hard; no model download or Calf. global_mapping has no exposed CancellationToken; no new stage after soft timeout.\n'+str(opts));p.verify_matches(db,sys.argv[2],options=opts,cancellation_token=token)
 with sqlite3.connect(db) as c:counts={'raw':c.execute('select count(*) from matches').fetchone()[0],'verified_nonempty':c.execute('select count(*) from two_view_geometries where rows>0').fetchone()[0],'all_verification_records':c.execute('select count(*) from two_view_geometries').fetchone()[0]}
 (root/'verification.json').write_text(json.dumps(counts,indent=2));print('verified',counts,flush=True)
 if time.monotonic()-start>=120:raise RuntimeError('soft_timeout_after_verify')
 with p.Database.open(db) as database:
  cams=database.read_all_cameras();assert len(cams)==1;camera=cams[0];camera.params=[604.17,960.,540.];camera.has_prior_focal_length=True;database.update_camera(camera)
 assert p.calibrate_view_graph(db,p.ViewGraphCalibrationOptions(random_seed=17))
 if time.monotonic()-start>=120:raise RuntimeError('soft_timeout_after_calibration')
 o=p.GlobalPipelineOptions(num_threads=4,random_seed=17,ignore_watermarks=True);o.mapper.num_threads=4;o.mapper.refine_sensor_from_rig=False;o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False;o.mapper.rotation_averaging.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_focal_length=True;o.mapper.bundle_adjustment.refine_extra_params=False;o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=4;o.mapper.bundle_adjustment.ceres.solver_options.max_num_iterations=30;o.mapper.keep_max_num_tracks=30000
 with (root/'options.txt').open('a') as f:f.write('\n'+str(o))
 models=p.global_mapping(db,prepared/'images',root/'models',options=o);softstop.cancel()
 from scripts.pilot.reconstruct_route import model_assessment
 reports=[]
 for identity,rec in models.items():
  if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
  geom,report=model_assessment(rec,prepared,166,0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
 (root/'report.json').write_text(json.dumps({'models':reports,'no_autoaccept':True,'physical_calibration_verified':False,'independent_pose_holdout':False},indent=2));print('components',len(models),flush=True);sys.exit()
raise SystemExit('Prepared only; invoke run after handoff.')
