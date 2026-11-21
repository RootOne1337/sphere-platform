"""Real two-view camera-relative diagnostics. No map, action or metric scale."""
import os,sys,time,pathlib,json,hashlib,subprocess,ctypes
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-image-route-20261101/relative-goals');base=root.parent;prep=pathlib.Path('.local-pilot/scooter-temporal-bridge-20261101/prepared');capture=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');maskpath=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png');G=1024**3
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 src=[base/'scores.npz',base/'query-metrics.json',base/'sequence-dp-results.json',base/'reference-receipt.json',prep/'reconstruction-input.json',maskpath,capture/'video.h264',capture/'manifest.json',capture/'frames.jsonl',pathlib.Path('motor_worker/image_route_relative.py')];before={str(p):sha(p) for p in src};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None;start=time.monotonic()
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())]);t=time.monotonic()
  with (root/'worker.log').open('w') as log:
   child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>60:reason='memory_guard' if min(v)<4.5*G else 'timeout';child.kill();child.wait();break
    time.sleep(.25)
   code=child.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in src};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'source_hashes_unchanged':before==after,'exit':code,'stop':reason,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'seconds':time.monotonic()-start,'owned_direct_child_only':True,'no_gpu_or_actions':True};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
if sys.argv[1:]!=['worker']:raise SystemExit('unsupported')
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2,math
from motor_worker.browser_teach import validate_browser,decoded_browser
from motor_worker.image_route_relative import estimate_relative_goal
cv2.setNumThreads(4);dp=json.loads((base/'sequence-dp-results.json').read_text())['forward']['rows'];raw=json.loads((base/'query-metrics.json').read_text())['queries'];z=np.load(base/'scores.npz');refs=z['reference_indices'];rt=z['reference_ticks_90k'];lookup={int(n):i for i,n in enumerate(refs)}
def future(name):
 at=lookup[int(name)];j=int(np.searchsorted(rt,rt[at]+54000,side='left'));return int(refs[j]) if j<len(refs) else None
dpeligible=[r for r in dp if r['chosen_reference_index'] is not None and future(r['chosen_reference_index']) is not None];chosen=[dpeligible[i] for i in np.linspace(0,len(dpeligible)-1,8).round().astype(int)];assert len({r['query_index'] for r in chosen})==8;chosenids={r['query_index'] for r in chosen};controls=[r for r in raw if r['high_score_wrong_over_2_seconds'] and r['query_index'] not in chosenids and future(r['predicted_reference_index']) is not None];assert len(controls)>=4;controls=[controls[i] for i in np.linspace(0,len(controls)-1,4).round().astype(int)]
plan=[{'role':'dp_selected','query_index':r['query_index'],'selected_reference_index':r['chosen_reference_index'],'target_reference_index':future(r['chosen_reference_index'])} for r in chosen]+[{'role':'raw_wrong_control','query_index':r['query_index'],'selected_reference_index':r['predicted_reference_index'],'target_reference_index':future(r['predicted_reference_index'])} for r in controls];assert len({r['query_index'] for r in plan})==12;(root/'selection.json').write_text(json.dumps({'selection':plan,'rule':'8 equally spaced entries in eligible DP-confirmed sequence; 4 equally spaced raw high-score wrong controls not in those queries; target = first reference >= selected reference time +0.6s; query timestamp NEVER used for target selection','raw_wrong_is_same_video_time_proxy_only':True},indent=2));print('selection',plan,flush=True)
precise=cv2.imread(str(maskpath),0);precise[int(1080*.975):]=0;mask=cv2.resize(precise,(960,540),interpolation=cv2.INTER_NEAREST);mask=cv2.erode(mask,np.ones((17,17),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0);sift=cv2.SIFT_create(nfeatures=2048,contrastThreshold=.0066667,edgeThreshold=10);bf=cv2.BFMatcher(cv2.NORM_L2);(root/'query-cache').mkdir(exist_ok=True);(root/'query-images').mkdir(exist_ok=True);qids={r['query_index'] for r in plan};queries={};start=time.monotonic()
for row,frame in decoded_browser(validate_browser(capture)):
 if row['index'] not in qids:continue
 bgr=frame.to_ndarray(format='bgr24');digest=hashlib.sha256(bgr.tobytes()).hexdigest();assert digest==next(r['bgr_sha256'] for r in raw if r['query_index']==row['index']);gray=cv2.resize(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY),(960,540),interpolation=cv2.INTER_AREA);kp,d=sift.detectAndCompute(gray,mask)
 if d is None:kp=[];d=np.empty((0,128),np.float32)
 if len(kp)>1024:
  keep=sorted(range(len(kp)),key=lambda i:(-kp[i].response,i))[:1024];kp=[kp[i] for i in keep];d=d[keep]
 if len(d):d=np.sqrt(d/np.maximum(d.sum(axis=1,keepdims=True),1e-8));d/=np.maximum(np.linalg.norm(d,axis=1,keepdims=True),1e-8)
 xy=np.asarray([p.pt for p in kp],np.float32).reshape(-1,2);qcache=root/'query-cache'/f"{row['index']:08d}.npz";np.savez(qcache,points=xy,descriptors=d.astype(np.float32));cv2.imwrite(str(root/'query-images'/f"{row['index']:08d}.jpg"),gray,[cv2.IMWRITE_JPEG_QUALITY,90]);queries[row['index']]={'ticks':row['relative_ticks_90k'],'bgr_sha256':digest,'access_unit_sha256':row['sha256'],'feature_count':len(xy),'cache_sha256':sha(qcache)}
assert set(queries)==qids and sum(p.stat().st_size for p in (root/'query-cache').iterdir())<=10*1024**2;K=np.array([[302.085,0,479.5],[0,302.085,269.5],[0,0,1.]],np.float64);results=[]
for row in plan:
 idx=row['query_index'];target=row['target_reference_index'];q=np.load(root/'query-cache'/f'{idx:08d}.npz');r=np.load(base/'cache'/f'{target:08d}.npz');qp,qd=q['points'],q['descriptors'];tp,td=r['points'],r['descriptors'];matches=bf.knnMatch(qd,td,k=2) if len(qd)>=2 and len(td)>=2 else [];good=sorted((p[0] for p in matches if len(p)==2 and p[0].distance<.75*p[1].distance),key=lambda x:x.distance);usedq=set();usedt=set();pairs=[]
 for x in good:
  a=tuple(map(float,qp[x.queryIdx]));b=tuple(map(float,tp[x.trainIdx]));
  if a not in usedq and b not in usedt:usedq.add(a);usedt.add(b);pairs.append((a,b))
 a=np.asarray([x[0] for x in pairs],np.float64).reshape(-1,2);b=np.asarray([x[1] for x in pairs],np.float64).reshape(-1,2);cv2.setRNGSeed(17);t=time.monotonic();result=estimate_relative_goal(a,b,K,width=960,height=540);seconds=time.monotonic()-t;R=result['Rtarget_from_query'];orientation=None
 if R is not None:
  R=np.asarray(R);orientation={'matrix_convention':'Rtarget_from_query; axis angles are algebraic camera-coordinate diagnostics, not vehicle yaw/pitch','yaw_y_rad':float(math.atan2(R[0,2],R[2,2])),'pitch_x_rad':float(math.atan2(-R[1,2],math.hypot(R[0,2],R[2,2])))}
 results.append({**row,**queries[idx],'target_cache_sha256':sha(base/'cache'/f'{target:08d}.npz'),'matched_unique_coordinates':len(pairs),'estimate_seconds':seconds,'rotation_angles':orientation,'relative':result,'same_video_proxy_delta_seconds':abs(int(queries[idx]['ticks'])-int(rt[lookup[target]]))/90000.})
(root/'report.json').write_text(json.dumps({'results':results,'intrinsics':K.tolist(),'intrinsics_status':'focal 604.17 at 1920px width scaled by .5; pixel-center cx479.5 cy269.5; physical calibration unverified','camera_to_vehicle_unknown':True,'units':'relative translation direction is unitless and never distance/speed; no ground path','query_time_never_used_for_target_selection':True,'cache_bytes':sum(p.stat().st_size for p in (root/'query-cache').iterdir()),'elapsed_s':time.monotonic()-start,'execution_qualified':False,'no_action':True},indent=2));print('results',[(x['role'],x['query_index'],x['relative']['status']) for x in results],flush=True)
