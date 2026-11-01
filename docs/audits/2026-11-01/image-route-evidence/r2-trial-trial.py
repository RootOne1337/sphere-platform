"""Isolated auto-index hook trial; SfM deliberately replaced by sentinel."""
import os,sys,time,pathlib,json,hashlib,subprocess,ctypes,threading
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/image-route-auto-trial-20261101-r2').resolve();source=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input').resolve();oldreview=source.parent/'image-route-review/review.json';job=root/'job';G=1024**3;names=('manifest.json','frames.jsonl','inputs.jsonl','video.h264','COMPLETE')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def memory():
 m=windows_memory();return [m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']]
if len(sys.argv)==1:
 assert not job.exists(),'trial_job_exists_do_not_overwrite';original={n:sha(source/n) for n in names};fused_before=sha(oldreview);initial=memory();assert min(initial)>=3*G,'admission_memory';job.mkdir();(job/'input').mkdir();identities={}
 for n in names:
  src=source/n;dst=job/'input'/n;assert src.is_file() and not src.is_symlink();os.link(src,dst);a,b=src.stat(),dst.stat();assert (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino) and sha(dst)==original[n];identities[n]={'device':a.st_dev,'inode':a.st_ino,'links':a.st_nlink}
 (root/'input-before.json').write_text(json.dumps({'source_sha256':original,'source_fused_review_sha256':fused_before,'hardlink_identity':identities,'input_read_only_verified_by_code_inspection':True},indent=2));env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())]);start=time.monotonic();samples=[];reason=None
 with (root/'trial-worker.log').open('w') as log:
  child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
  while child.poll() is None:
   v=memory();samples.append(v)
   if min(v)<2*G or time.monotonic()-start>195:
    reason='memory_guard' if min(v)<2*G else 'external_timeout';(job/'CANCEL').touch(exist_ok=True)
    try:child.wait(timeout=8)
    except subprocess.TimeoutExpired:
     subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=10,check=False);child.wait(timeout=5)
    break
   time.sleep(.25)
  code=child.returncode
 after={n:sha(source/n) for n in names};linked_after={n:sha(job/'input'/n) for n in names};receipt={'exit':code,'stop':reason,'seconds':time.monotonic()-start,'source_sha256_before':original,'source_sha256_after':after,'linked_sha256_after':linked_after,'source_and_links_unchanged':original==after==linked_after,'existing_fused_review_unchanged':fused_before==sha(oldreview),'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((v[0] for v in samples),default=None),'min_commit':min((v[1] for v in samples),default=None),'worker_log_bytes':(job/'image-route-workspace/worker.log').stat().st_size if (job/'image-route-workspace/worker.log').exists() else None,'real_reconstruct_hook':True,'real_normal_builder_child':True,'sfm_sentinel_only':True,'gpu_disabled':True,'execution_qualified':False,'physical_actions':0};(root/'trial-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True);sys.exit()
if sys.argv[1:]!=['worker']:raise SystemExit('unsupported')
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];process=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(process,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(process,ctypes.c_size_t(sum(bits[:4])))
class PE(ctypes.Structure):
 _fields_=[('size',ctypes.c_ulong),('usage',ctypes.c_ulong),('pid',ctypes.c_ulong),('heap',ctypes.c_size_t),('module',ctypes.c_ulong),('threads',ctypes.c_ulong),('parent',ctypes.c_ulong),('priority',ctypes.c_long),('flags',ctypes.c_ulong),('name',ctypes.c_wchar*260)]
class MC(ctypes.Structure):
 _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong),('peak',ctypes.c_size_t),('rss',ctypes.c_size_t),('qp',ctypes.c_size_t),('q',ctypes.c_size_t),('qnp',ctypes.c_size_t),('qn',ctypes.c_size_t),('pagefile',ctypes.c_size_t),('peakpagefile',ctypes.c_size_t)]
k.CreateToolhelp32Snapshot.argtypes=[ctypes.c_ulong,ctypes.c_ulong];k.CreateToolhelp32Snapshot.restype=ctypes.c_void_p;k.Process32FirstW.argtypes=[ctypes.c_void_p,ctypes.POINTER(PE)];k.Process32NextW.argtypes=[ctypes.c_void_p,ctypes.POINTER(PE)];k.CloseHandle.argtypes=[ctypes.c_void_p];k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
observed={};max_aggregate=0;done=threading.Event();owned=[]
def monitor():
 global max_aggregate
 while not done.wait(.25):
  snap=k.CreateToolhelp32Snapshot(2,0);items=[];e=PE();e.size=ctypes.sizeof(e);ok=k.Process32FirstW(snap,ctypes.byref(e))
  while ok:items.append((int(e.pid),int(e.parent),e.name));ok=k.Process32NextW(snap,ctypes.byref(e))
  k.CloseHandle(snap);members={os.getpid()};changed=True
  while changed:
   add={pid for pid,parent,_ in items if parent in members};changed=not add<=members;members|=add
  total=0
  for pid,parent,name in items:
   if pid not in members:continue
   h=k.OpenProcess(0x1000,0,pid)
   if not h:continue
   c=MC();c.cb=ctypes.sizeof(c)
   if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(h),ctypes.byref(c),c.cb):
    total+=c.rss;entry=observed.setdefault(str(pid),{'name':name,'peak_working_set_bytes':0});entry['peak_working_set_bytes']=max(entry['peak_working_set_bytes'],c.peak)
   k.CloseHandle(h)
  max_aggregate=max(max_aggregate,total)
thread=threading.Thread(target=monitor,daemon=True);thread.start()
from scripts.pilot import reconstruct_route as route,route_hud_workspace as hud
real_popen=subprocess.Popen
def tracked_popen(*args,**kwargs):
 p=real_popen(*args,**kwargs);owned.append(p);(root/'owned-builder-pid.json').write_text(json.dumps({'pid':p.pid,'command_module':'scripts.pilot.image_route_builder'}));return p
subprocess.Popen=tracked_popen
def guard(path):
 if (path/'CANCEL').exists():raise RuntimeError('cancelled')
 if min(memory())<2*G:raise RuntimeError('resource_guard')
route.checkpoint=lambda p,**kwargs:guard(p);route.make_observation_checkpoint=lambda p,**kwargs:lambda:guard(p);hud.start=lambda *args,**kwargs:None
class SfMNotRun(Exception):pass
def sentinel(*args,**kwargs):
 (root/'sfm-sentinel.json').write_text(json.dumps({'called':True,'sfm_executed':False,'gpu_executed':False}));raise SfMNotRun()
route._reconstruct=sentinel;started=time.monotonic()
try:route.reconstruct(job,'game',30000,route_only=True)
except SfMNotRun:outcome='sentinel_expected'
except Exception as e:outcome='unexpected_'+type(e).__name__;print('trial_error',repr(e),flush=True)
finally:
 done.set();thread.join(3)
 for p in owned:
  if p.poll() is None:
   (job/'CANCEL').touch(exist_ok=True)
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
status=json.loads((job/'image-route-workspace/state.json').read_text()) if (job/'image-route-workspace/state.json').exists() else None;result={'outcome':outcome,'workspace_state':status,'builder_children':[{'pid':p.pid,'exit':p.poll()} for p in owned],'all_children_exited':all(p.poll() is not None for p in owned),'elapsed_seconds':time.monotonic()-started,'peak_aggregate_observed_working_set_bytes':max_aggregate,'owned_processes':observed,'sfm_stubbed':True,'physical_actions':0}
if (job/'image-route-review/review.json').is_file():
 from scripts.pilot.image_route_review import read_image_route_review
 review=json.loads(read_image_route_review(job));samples=review['samples'];selected=[r for r in samples if r['sequence_reference_ticks_90k'] is not None];result['review']={'source_manifest_sha256':review['source_manifest_sha256'],'samples':len(samples),'references':len(review['reference_ticks_90k']),'selected':len(selected),'unknown_or_ambiguous':len(samples)-len(selected),'same_video_hit_within_0_6':sum(abs(r['sequence_reference_ticks_90k']-r['ticks_90k'])<=54000 for r in selected),'same_video_wrong_over_2':sum(abs(r['sequence_reference_ticks_90k']-r['ticks_90k'])>180000 for r in selected),'denominator_all_samples':len(samples),'time_labels_only_for_evaluation':True,'execution_qualified':False};producer=json.loads((job/'image-route-review/producer.json').read_text());result['producer']={k:producer.get(k) for k in ('cache_bytes','source_unchanged','analysis_shape','references','limit_seconds')};result['producer']['references']=len(producer.get('references',[]))
(root/'worker-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

