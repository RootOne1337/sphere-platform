"""Bounded offline same-source image retrieval; not a navigator."""
import os,sys,time,pathlib,json,hashlib,subprocess,ctypes
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-image-route-20261101');prep=pathlib.Path('.local-pilot/scooter-temporal-bridge-20261101/prepared');capture=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');maskpath=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png');baseline=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');G=1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 source=[capture/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[prep/'reconstruction-input.json',maskpath,baseline/'database.db']+sorted((baseline/'models/0').glob('*.bin'));before={str(x):sha(x) for x in source};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None;start=time.monotonic()
 if min(initial)>=6*G:
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())]);t=time.monotonic()
  with (root/'worker.log').open('w') as log:
   child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
   (root/'worker-pid.json').write_text(json.dumps({'owned_pid':child.pid,'executable':sys._base_executable}))
   while child.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>240:reason='memory_guard' if min(v)<4.5*G else 'timeout';child.kill();child.wait();break
    time.sleep(.4)
   code=child.returncode
 else:reason='admission_memory'
 after={str(x):sha(x) for x in source};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'inputs_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'exit':code,'stop':reason,'seconds':time.monotonic()-start,'owned_direct_child_only':True,'no_device_or_network':True};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
if sys.argv[1:]!=['worker']:raise SystemExit('unsupported')
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
from motor_worker.browser_teach import validate_browser,decoded_browser
cv2.setNumThreads(4);meta=json.loads((prep/'reconstruction-input.json').read_text());refs=meta['images'];assert len(refs)==169 and sha(capture/'manifest.json')==meta['source_manifest_sha256'];indices=np.array([r['source_index'] for r in refs],np.int32);ticks=np.array([r['relative_ticks_90k'] for r in refs],np.int64);assert np.all(np.diff(indices)>0) and np.all(np.diff(ticks)>0)
class MemoryCounters(ctypes.Structure):
 _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong),('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
def rss():
 p=MemoryCounters();p.cb=ctypes.sizeof(p);assert ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(proc),ctypes.byref(p),p.cb);return {'working_set_bytes':p.WorkingSetSize,'peak_working_set_bytes':p.PeakWorkingSetSize,'peak_pagefile_bytes':p.PeakPagefileUsage}
capturedata=validate_browser(capture);assert len(capturedata.frames)==901;reference_set=set(map(int,indices));available=np.array([i for i in range(901) if i not in reference_set]);targets=np.linspace(0,900,100);used=set();qids=[]
for target in targets:
 for candidate in available[np.argsort(abs(available-target),kind='stable')]:
  if int(candidate) not in used:used.add(int(candidate));qids.append(int(candidate));break
qids.sort();(root/'cache').mkdir(exist_ok=True);(root/'query-images').mkdir(exist_ok=True);precise=cv2.imread(str(maskpath),0);assert precise.shape==(1080,1920);precise[int(1080*.975):]=0;mask=cv2.resize(precise,(960,540),interpolation=cv2.INTER_NEAREST);mask=cv2.erode(mask,np.ones((17,17),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0);smallmask=cv2.resize(mask,(85,48),interpolation=cv2.INTER_NEAREST)>0;sift=cv2.SIFT_create(nfeatures=2048,contrastThreshold=.0066667,edgeThreshold=10);bf=cv2.BFMatcher(cv2.NORM_L2)
def extract(gray):
 kp,d=sift.detectAndCompute(gray,mask)
 if d is None:return np.empty((0,2),np.float32),np.empty((0,128),np.float32)
 if len(kp)>1024:
  keep=sorted(range(len(kp)),key=lambda i:(-kp[i].response,i))[:1024];kp=[kp[i] for i in keep];d=d[keep]
 d=np.sqrt(d/np.maximum(d.sum(axis=1,keepdims=True),1e-8));d/=np.maximum(np.linalg.norm(d,axis=1,keepdims=True),1e-8);return np.asarray([p.pt for p in kp],np.float32),d.astype(np.float32)
def coarse(gray):
 a=cv2.resize(gray,(85,48),interpolation=cv2.INTER_AREA).astype(np.float32)/255.;mean=float(a[smallmask].mean());a=np.where(smallmask,a,mean).astype(np.float32);a-=mean;d=cv2.dct(a)[:12,:16].ravel()[1:];return d/max(float(np.linalg.norm(d)),1e-12)
started=time.monotonic();descs=[];points=[];globals_=[];ref_rgb_hashes=set();cache_bytes=0
for i,r in enumerate(refs):
 file=prep/r['image'];assert sha(file)==r['png_sha256'];bgr=cv2.imread(str(file));assert bgr is not None and bgr.shape==(1080,1920,3);ref_rgb_hashes.add(hashlib.sha256(bgr.tobytes()).hexdigest());gray=cv2.resize(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY),(960,540),interpolation=cv2.INTER_AREA);pt,d=extract(gray);v=coarse(gray);file=root/'cache'/f'{int(indices[i]):08d}.npz';np.savez(file,points=pt,descriptors=d,coarse=v);cache_bytes+=file.stat().st_size;assert cache_bytes<=100*1024**2;points.append(pt);descs.append(d);globals_.append(v)
 if (i+1)%25==0:print('reference',i+1,'/',len(refs),flush=True)
globalmat=np.asarray(globals_,np.float32);(root/'reference-receipt.json').write_text(json.dumps({'source_manifest_sha256':meta['source_manifest_sha256'],'frames':169,'indices':indices.tolist(),'ticks_90k':ticks.tolist(),'cache_bytes':cache_bytes,'max_cache_bytes':100*1024**2,'opencv':cv2.__version__,'settings':'960x540, SIFT2048 detector cap then strongest1024 after precise-HUD mask+8px erode, RootSIFT; DCT 85x48 low frequency, no DNN','seconds':time.monotonic()-started},indent=2));print('reference cache complete',cache_bytes,flush=True)
scores=np.zeros((100,169),np.float32);checked=np.zeros((100,169),bool);excluded=np.zeros((100,169),bool);qticks=np.full(100,-1,np.int64);actual_indices=np.full(100,-1,np.int32);metrics=[];duplicates=[];qmap={n:i for i,n in enumerate(qids)};decoded=0;times={'decode_and_queries_s':0.,'extract_s':0.,'coarse_s':0.,'matching_s':0.};query_start=time.monotonic()
def checkpoint():
 np.savez_compressed(root/'scores.npz',scores=scores,checked=checked,excluded=excluded,query_indices=actual_indices,query_ticks_90k=qticks,reference_indices=indices,reference_ticks_90k=ticks);(root/'query-metrics.json').write_text(json.dumps({'queries':metrics,'duplicate_query_indices':duplicates,'timing':times,'process_memory':rss(),'note':'Same-video offline timestamp labels; not an independent repeat. Unprocessed rows have query index -1.'},indent=2))
for row,frame in decoded_browser(capturedata):
 decoded+=1;idx=row['index']
 if idx not in qmap:continue
 q=qmap[idx];bgr=frame.to_ndarray(format='bgr24');assert bgr.shape==(1080,1920,3);digest=hashlib.sha256(bgr.tobytes()).hexdigest()
 if digest in ref_rgb_hashes:duplicates.append(idx);continue
 actual_indices[q]=idx;qticks[q]=row['relative_ticks_90k'];t=time.monotonic();gray=cv2.resize(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY),(960,540),interpolation=cv2.INTER_AREA);qp,qd=extract(gray);times['extract_s']+=time.monotonic()-t;cv2.imwrite(str(root/'query-images'/f'{idx:08d}.jpg'),gray,[cv2.IMWRITE_JPEG_QUALITY,85]);t=time.monotonic();v=coarse(gray);distance=np.linalg.norm(globalmat-v,axis=1);exclude=np.abs(ticks-qticks[q])<=int(.15*90000);excluded[q]=exclude;distance[exclude]=np.inf;top=np.argsort(distance,kind='stable')[:8];times['coarse_s']+=time.monotonic()-t;t=time.monotonic();details=[]
 for j in top:
  j=int(j);checked[q,j]=True;rd=descs[j];rp=points[j];detail={'reference_index':int(indices[j]),'coarse_distance':float(distance[j]),'query_keypoints':len(qp),'reference_keypoints':len(rp),'matches':0,'inliers':0,'fraction':0.,'occupied_cells':0,'score':0.}
  if len(qd)>=2 and len(rd)>=2:
   knn=bf.knnMatch(qd,rd,k=2);good=[pair[0] for pair in knn if len(pair)==2 and pair[0].distance<.75*pair[1].distance];unique={}
   for z in good:
    if z.trainIdx not in unique or z.distance<unique[z.trainIdx].distance:unique[z.trainIdx]=z
   good=list(unique.values());detail['matches']=len(good)
   if len(good)>=20:
    qxy=np.float32([qp[z.queryIdx] for z in good]);rxy=np.float32([rp[z.trainIdx] for z in good]);cv2.setRNGSeed(17);F,im=cv2.findFundamentalMat(qxy,rxy,cv2.FM_RANSAC,1.5,.999,2000)
    if F is not None and im is not None:
     flags=im.ravel().astype(bool);count=int(flags.sum());fraction=count/len(good);accepted=qxy[flags];cells=np.floor(accepted/[960,540]*4).astype(int);occupied=len(np.unique(cells[:,1]*4+cells[:,0])) if count else 0;score=min(count/80.,1.)*fraction*min((occupied/16.)/.35,1.) if count>=20 and fraction>=.35 and occupied>=4 else 0.;scores[q,j]=score;detail.update(inliers=count,fraction=fraction,occupied_cells=int(occupied),score=float(score))
  details.append(detail)
 times['matching_s']+=time.monotonic()-t;winner=int(np.argmax(scores[q]));best=float(scores[q,winner]);pred=int(indices[winner]) if best>0 else None;delta=abs(int(ticks[winner])-int(qticks[q]))/90000 if best>0 else None;metrics.append({'query_index':idx,'ticks_90k':int(qticks[q]),'bgr_sha256':digest,'query_features':len(qp),'predicted_reference_index':pred,'score':best,'same_video_time_error_seconds':delta,'hit_within_0_6_seconds':bool(delta is not None and delta<=.6),'high_score_wrong_over_2_seconds':bool(best>=.35 and delta is not None and delta>2),'details':details});
 if len(metrics)%5==0:times['decode_and_queries_s']=time.monotonic()-query_start;checkpoint();print('queries',len(metrics),'decoded',decoded,flush=True)
times['decode_and_queries_s']=time.monotonic()-query_start;checkpoint();valid=actual_indices>=0;total=int(valid.sum());h=sum(x['hit_within_0_6_seconds'] for x in metrics);wrong=sum(x['high_score_wrong_over_2_seconds'] for x in metrics);(root/'summary.json').write_text(json.dumps({'reference_views':169,'requested_queries':100,'completed_queries':total,'duplicates_excluded':len(duplicates),'all_901_frames_decoded':decoded==901,'score_threshold_high':.35,'hits_within_0_6s':h,'high_score_wrong_over_2s':wrong,'queries_without_positive_score':sum(x['score']==0 for x in metrics),'timings':times,'source_manifest_sha256':meta['source_manifest_sha256'],'interpretation':'Same-source temporal labels only; no independent repeated traversal or localization truth. ±0.15s excluded per query; no elapsed-time ranking or filter feedback; excluded/unchecked candidate scores are zero but tracked separately. No pose/control inference, no promotion.'},indent=2));print('completed',total,'hits',h,'wrong',wrong,flush=True)
