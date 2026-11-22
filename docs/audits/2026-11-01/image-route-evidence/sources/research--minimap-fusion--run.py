"""Game-specific minimap auxiliary test; no map position or device actions."""
import os,sys,time,pathlib,json,hashlib,subprocess,ctypes,ast
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-image-route-20261101/minimap-fusion');base=root.parent;prep=pathlib.Path('.local-pilot/scooter-temporal-bridge-20261101/prepared');capture=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');G=1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 intent={'roi_original_px':[0,0,310,320],'center_original':[145,165],'outer_radius':108,'center_exclusion_radius':28,'badge_exclusion_center':[241,238],'badge_exclusion_radius':57,'dynamic_HSV_exclusion':'S>55 or V>205 or V<25; erode 3x3','crop_original_xyxy':[37,57,253,273],'resized':[96,96],'matching':'masked zero-normalized correlation of Gaussian-smoothed Sobel edge magnitudes; center-fixed rotate [-30,-20,-10,0,10,20,30], scale [.9,1,1.1], choose maximum','min_valid_fraction_of_static_geometry':.30,'min_edge_std':.02,'fusion':'world**.7 * max(0,(NCC+1)/2)**.3 for valid auxiliary, otherwise world unchanged; unchecked remains unchecked','evaluation':'same-video proxy only, 100 forward/reverse causal DP unchanged','no_pose_or_action':True,'frozen_before_evaluation':True};(root/'intent.json').write_text(json.dumps(intent,indent=2));src=[base/'scores.npz',base/'query-metrics.json',base/'sequence-dp.py',base/'sequence-dp-intent.json',base/'sequence-dp-results.json',prep/'reconstruction-input.json',capture/'video.h264',capture/'manifest.json',capture/'frames.jsonl',pathlib.Path('.local-pilot/scooter-minimap-20261101/experiment.py')];before={str(p):sha(p) for p in src};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None;start=time.monotonic()
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())]);t=time.monotonic()
  with (root/'worker.log').open('w') as log:
   child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>90:reason='memory_guard' if min(v)<4.5*G else 'timeout';child.kill();child.wait();break
    time.sleep(.25)
   code=child.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in src};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'input_hashes_unchanged':before==after,'exit':code,'stop':reason,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'seconds':time.monotonic()-start,'owned_direct_child_only':True,'no_gpu_or_actions':True};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
if sys.argv[1:]!=['worker']:raise SystemExit('unsupported')
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
from motor_worker.browser_teach import validate_browser,decoded_browser
cv2.setNumThreads(4);z=np.load(base/'scores.npz');world=z['scores'];checked=z['checked'];excluded=z['excluded'];idx=z['query_indices'];ticks=z['query_ticks_90k'];refidx=z['reference_indices'];rt=z['reference_ticks_90k'];records=json.loads((base/'query-metrics.json').read_text())['queries'];query={r['query_index']:r for r in records};meta=json.loads((prep/'reconstruction-input.json').read_text());refmeta={r['source_index']:r for r in meta['images']};assert len(refmeta)==169 and sha(capture/'manifest.json')==meta['source_manifest_sha256'];assert world.shape==(100,169) and not np.any(checked&excluded);needed=set(map(int,idx))|set(map(int,refidx))|{110,275,115,510,567};cap=validate_browser(capture);yy,xx=np.indices((320,310));rad=(xx-145)**2+(yy-165)**2;static=(rad<=108**2)&(rad>=28**2)&((xx-241)**2+(yy-238)**2>57**2);static96=cv2.resize(static[57:273,37:253].astype(np.uint8),(96,96),interpolation=cv2.INTER_NEAREST).astype(bool);static_count=int(static96.sum());crops={};decoded=0
for row,frame in decoded_browser(cap):
 decoded+=1;i=row['index']
 if i not in needed:continue
 bgr=frame.to_ndarray(format='bgr24');rgb=cv2.cvtColor(bgr[:320,:310],cv2.COLOR_BGR2RGB);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);valid=static.copy();valid[(hsv[:,:,1]>55)|(hsv[:,:,2]>205)|(hsv[:,:,2]<25)]=False;valid=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8));small=cv2.resize(gray[57:273,37:253],(96,96),interpolation=cv2.INTER_AREA);vm=cv2.resize(valid[57:273,37:253],(96,96),interpolation=cv2.INTER_NEAREST).astype(bool);smoothed=cv2.GaussianBlur(small,(5,5),0).astype(np.float32)/255.;gx=cv2.Sobel(smoothed,cv2.CV_32F,1,0,ksize=3,scale=.25);gy=cv2.Sobel(smoothed,cv2.CV_32F,0,1,ksize=3,scale=.25);edge=cv2.magnitude(gx,gy);crops[i]={'gray':small,'valid':vm,'edge':edge}
 if i in query:assert hashlib.sha256(bgr.tobytes()).hexdigest()==query[i]['bgr_sha256']
 if i in refmeta:assert row['sha256']==refmeta[i]['source_access_unit_sha256'] and row['relative_ticks_90k']==refmeta[i]['relative_ticks_90k']
assert needed<=crops.keys() and decoded==901
transforms=[]
for scale in (.9,1.,1.1):
 for angle in (-30,-20,-10,0,10,20,30):transforms.append((angle,scale,cv2.getRotationMatrix2D((48,48),angle,scale)))
aux=np.zeros_like(world);validaux=np.zeros_like(checked);details=[]
for i in range(100):
 q=crops[int(idx[i])];qmask=q['valid'];qe=q['edge'];rowout=[]
 for j in np.flatnonzero(checked[i]):
  target=crops[int(refidx[j])];best=None
  for angle,scale,M in transforms:
   edge=cv2.warpAffine(target['edge'],M,(96,96),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT);mask=cv2.warpAffine(target['valid'].astype(np.uint8),M,(96,96),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT).astype(bool);v=qmask&mask;count=int(v.sum())
   if count<.30*static_count:continue
   a=qe[v].astype(np.float64);b=edge[v].astype(np.float64);a-=a.mean();b-=b.mean();sa=float(np.sqrt(np.mean(a*a)));sb=float(np.sqrt(np.mean(b*b)))
   if min(sa,sb)<.02:continue
   ncc=float(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)),-1,1))
   if best is None or ncc>best['ncc']:best={'ncc':ncc,'angle':angle,'scale':scale,'valid_fraction':count/static_count,'std_query':sa,'std_target':sb}
  if best is not None:validaux[i,j]=True;aux[i,j]=best['ncc'];rowout.append({'reference_index':int(refidx[j]),**best})
 details.append({'query_index':int(idx[i]),'valid_pairs':rowout})
 if (i+1)%20==0:print('pairs queries',i+1,flush=True)
fused=world.copy();norm=np.maximum(0,(aux+1)/2);fused[validaux]=(world[validaux]**.7)*(norm[validaux]**.3);assert not np.any(validaux&~checked);np.savez_compressed(root/'fusion-scores.npz',scores=fused,world_scores=world,aux_ncc=aux,aux_valid=validaux,checked=checked,excluded=excluded,query_indices=idx,query_ticks_90k=ticks,reference_indices=refidx,reference_ticks_90k=rt);(root/'aux-details.json').write_text(json.dumps({'static_mask_pixels':static_count,'queries':details,'caveat':'Best of 21 transformations is selection-biased; not metric position or independently validated map matching.'},indent=2))
# Execute only the unmodified run() function from the frozen DP source, once on world and once on fused scores.
tree=ast.parse((base/'sequence-dp.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run');ns={'np':np,'scores':world,'checked':checked,'idx':idx,'ticks':ticks,'refidx':refidx,'rt':rt,'query':query};exec(compile(ast.Module(body=[fn],type_ignores=[]),'frozen_sequence_dp','exec'),ns);wfor=ns['run'](range(100));wrev=ns['run'](range(99,-1,-1));baseline=json.loads((base/'sequence-dp-results.json').read_text());assert wfor['summary']==baseline['forward']['summary'] and wrev['summary']==baseline['reverse']['summary'];ns['scores']=fused;ffor=ns['run'](range(100));frev=ns['run'](range(99,-1,-1))
def rawstats(s):
 hit=wrong=unknown=0
 for i in range(100):
  j=int(np.argmax(s[i]));best=float(s[i,j]);delta=abs(int(rt[j])-int(ticks[i]))/90000.;unknown+=int(best<=0);hit+=int(best>0 and delta<=.6);wrong+=int(best>=.35 and delta>2)
 return {'queries':100,'hits_within_0_6s':hit,'high_score_wrong_over_2s':wrong,'unknown':unknown}
summary={'raw_world':rawstats(world),'raw_fused':rawstats(fused),'dp_world_forward':wfor['summary'],'dp_fused_forward':ffor['summary'],'dp_world_reverse':wrev['summary'],'dp_fused_reverse':frev['summary'],'aux_checked_pairs':int(checked.sum()),'aux_valid_pairs':int(validaux.sum()),'aux_unknown_pairs':int((checked&~validaux).sum()),'decoded_source_frames':decoded,'same_video_only':True,'not_calibrated':True,'no_action':True};(root/'summary.json').write_text(json.dumps(summary,indent=2));(root/'dp-results.json').write_text(json.dumps({'forward':ffor,'reverse':frev,'caveat':'No independent repeat; same-video temporal proxy; no physical location, control or navigation qualification.'},indent=2));(root/'crop-cache.npz').write_bytes(b'') if False else None;np.savez_compressed(root/'display-crops.npz',indices=np.array(sorted(needed)),gray=np.array([crops[i]['gray'] for i in sorted(needed)]),valid=np.array([crops[i]['valid'] for i in sorted(needed)]));print(json.dumps(summary),flush=True)
