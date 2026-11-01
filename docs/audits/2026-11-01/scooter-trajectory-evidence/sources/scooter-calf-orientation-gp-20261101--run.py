import os,sys,time,pathlib,json,hashlib,subprocess,ctypes
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-calf-orientation-gp-20261101');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');ada=pathlib.Path('.local-pilot/scooter-orientation-prior-20261101');cap=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');G=1024**3
source=sorted((base/'models/0').glob('*.bin'))+[base/'prepared/reconstruction-input.json',ada/'adapter.py',ada/'adapter-fixture.json',pathlib.Path('.local-pilot/scooter-calfvo-full-20261101/candidate.npz'),pathlib.Path('.local-pilot/reconstruction-tools/calfvo-models/calfvo_dinov2.pth'),pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png'),cap/'video.h264',cap/'manifest.json',cap/'frames.jsonl',cap/'inputs.jsonl']
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 start=time.monotonic();m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];before={str(x):sha(x) for x in source};(root/'hash-before.json').write_text(json.dumps(before,indent=2));samples=[];reason=None;code=None
 m=windows_memory();admission=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']]
 if min(admission)>=6.5*G:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve());t=time.monotonic()
  with (root/'solver.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'solve'],stdout=log,stderr=subprocess.STDOUT,env=env)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>180:
     reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.4)
   code=p.returncode
 else:reason='admission_memory'
 after={str(x):sha(x) for x in source};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'input_hashes_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'exit':code,'stop':reason,'wall_seconds_including_hashes':time.monotonic()-start,'only_owned_child_terminated':True,'admission_min_GiB':6.5,'runtime_min_GiB':4.5};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
sys.path.insert(0,str(ada.resolve()));import adapter
import numpy as np,pycolmap as p
prepared=json.loads((base/'prepared/reconstruction-input.json').read_text());z=np.load(adapter.CANDIDATE,allow_pickle=False);rots,binding=adapter.bind_rotations(z['trajectory_c2w'],z['frame_indices'],z['ticks_90k'],prepared);rec,pre=adapter.prepare_reconstruction(base/'models/0',rots);opts=adapter.global_positioning_options();(root/'setup.json').write_text(json.dumps({'binding':binding,'preconditions':pre,'options':str(opts),'pose_graph':'empty: only point-to-camera constraints','random_positions_and_points':True,'source_tracks':'existing SIFT >=3 views','calf_translations_used':False,'cpu_affinity':4,'GP_solver_maxiter_threads_not_exposed':True,'calf_rotations_are_truth':False},indent=2));print('preconditions',pre,'begin GP',flush=True)
ok=p.run_global_positioning(opts,p.PoseGraph(),rec);print('global_positioning_return',ok,flush=True)
if not ok:raise RuntimeError('global_positioning_failed')
shift=adapter.center_first_camera_gauge(rec,binding['first_image']);gp=root/'gp-model';gp.mkdir();rec.write(gp);(root/'gp-receipt.json').write_text(json.dumps({'status':'completed','first_center_gauge_shift':shift,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'accepted':False},indent=2));print('GP saved; begin fixed-rotation BA',flush=True)
ba=adapter.ba_options(fixed_rotations=True);p.bundle_adjustment(rec,ba);maxerr=max(float(np.max(np.abs(im.cam_from_world().rotation.matrix()-rots[im.name].T))) for im in rec.images.values());assert maxerr<1e-7,maxerr
shift=adapter.center_first_camera_gauge(rec,binding['first_image']);out=root/'fixed-r-ba-model';out.mkdir();rec.write(out);(root/'fixed-r-ba-receipt.json').write_text(json.dumps({'status':'completed','options':str(ba),'max_rotation_abs_difference':maxerr,'first_center_gauge_shift':shift,'accepted':False},indent=2));print('fixed R BA saved',flush=True)
