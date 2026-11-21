"""One PTS-paced open-loop video replay, latest-frame-only, no device inputs."""
import os,sys,time,pathlib,json,hashlib,subprocess,ctypes,threading
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-image-route-20261101/stream_replay');base=root.parent;capture=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');prep=pathlib.Path('.local-pilot/scooter-temporal-bridge-20261101/prepared');maskpath=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png');G=1024**3
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 src=[capture/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[prep/'reconstruction-input.json',maskpath,base/'scores.npz',base/'minimap-fusion/display-crops.npz',base/'minimap-fusion/intent.json',pathlib.Path('motor_worker/image_route_sequence.py')]+sorted((base/'cache').glob('*.npz'));assert len(list((base/'cache').glob('*.npz')))==169;before={str(p):sha(p) for p in src};(root/'hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];reason=None;code=None;start=time.monotonic()
 if min(initial)>=6*G:
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())]);t=time.monotonic()
  with (root/'worker.log').open('w') as log:
   child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
   (root/'worker-pid.json').write_text(json.dumps({'owned_pid':child.pid,'executable':sys._base_executable}))
   while child.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-t>90:reason='memory_guard' if min(v)<4.5*G else 'timeout';child.kill();child.wait();break
    time.sleep(.25)
   code=child.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in src};(root/'hash-after.json').write_text(json.dumps(after,indent=2));receipt={'inputs_unchanged':before==after,'exit':code,'stop':reason,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'seconds_including_hashes':time.monotonic()-start,'owned_direct_child_only':True,'no_gpu_or_actions':True};(root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True);sys.exit()
if sys.argv[1:]!=['worker']:raise SystemExit('unsupported')
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import cv2,numpy as np
from motor_worker.browser_teach import validate_browser,decoded_browser
from motor_worker.image_route_sequence import CausalSequenceBeam
cv2.setNumThreads(4);meta=json.loads((prep/'reconstruction-input.json').read_text());refs=meta['images'];assert len(refs)==169 and sha(capture/'manifest.json')==meta['source_manifest_sha256'];indices=np.array([r['source_index'] for r in refs]);ticks=np.array([r['relative_ticks_90k'] for r in refs],np.int64);beam=CausalSequenceBeam(tuple(float(x)/90000. for x in ticks));capturedata=validate_browser(capture);assert len(capturedata.frames)==901;refpt=[];refdesc=[];refcoarse=[]
for i in indices:
 with np.load(base/'cache'/f'{i:08d}.npz') as z:refpt.append(z['points'].copy());refdesc.append(z['descriptors'].copy());refcoarse.append(z['coarse'].copy())
refcoarse=np.asarray(refcoarse,np.float32);precise=cv2.imread(str(maskpath),0);precise[int(1080*.975):]=0;mask=cv2.resize(precise,(960,540),interpolation=cv2.INTER_NEAREST);mask=cv2.erode(mask,np.ones((17,17),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0);smallmask=cv2.resize(mask,(85,48),interpolation=cv2.INTER_NEAREST)>0;sift=cv2.SIFT_create(nfeatures=2048,contrastThreshold=.0066667,edgeThreshold=10);bf=cv2.BFMatcher(cv2.NORM_L2)
def extract(gray):
 kp,d=sift.detectAndCompute(gray,mask)
 if d is None:return np.empty((0,2),np.float32),np.empty((0,128),np.float32)
 if len(kp)>1024:keep=sorted(range(len(kp)),key=lambda i:(-kp[i].response,i))[:1024];kp=[kp[i] for i in keep];d=d[keep]
 d=np.sqrt(d/np.maximum(d.sum(axis=1,keepdims=True),1e-8));d/=np.maximum(np.linalg.norm(d,axis=1,keepdims=True),1e-8);return np.asarray([p.pt for p in kp],np.float32),d.astype(np.float32)
def coarse(gray):
 a=cv2.resize(gray,(85,48),interpolation=cv2.INTER_AREA).astype(np.float32)/255.;mean=float(a[smallmask].mean());a=np.where(smallmask,a,mean).astype(np.float32);a-=mean;d=cv2.dct(a)[:12,:16].ravel()[1:];return d/max(float(np.linalg.norm(d)),1e-12)
def edge(gray):
 s=cv2.GaussianBlur(gray,(5,5),0).astype(np.float32)/255.;return cv2.magnitude(cv2.Sobel(s,cv2.CV_32F,1,0,ksize=3,scale=.25),cv2.Sobel(s,cv2.CV_32F,0,1,ksize=3,scale=.25))
yy,xx=np.indices((320,310));rad=(xx-145)**2+(yy-165)**2;static=(rad<=108**2)&(rad>=28**2)&((xx-241)**2+(yy-238)**2>57**2);static96=cv2.resize(static[57:273,37:253].astype(np.uint8),(96,96),interpolation=cv2.INTER_NEAREST).astype(bool);static_count=int(static96.sum());transforms=[cv2.getRotationMatrix2D((48,48),a,s) for s in (.9,1.,1.1) for a in (-30,-20,-10,0,10,20,30)];display=np.load(base/'minimap-fusion/display-crops.npz');displaymap={int(x):i for i,x in enumerate(display['indices'])};refwarp=[]
for i in indices:
 j=displaymap[int(i)];e=edge(display['gray'][j]);m=display['valid'][j].astype(np.uint8);refwarp.append([(cv2.warpAffine(e,M,(96,96),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT),cv2.warpAffine(m,M,(96,96),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT).astype(bool)) for M in transforms])
def minimap(bgr):
 rgb=cv2.cvtColor(bgr[:320,:310],cv2.COLOR_BGR2RGB);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);v=static.copy();v[(hsv[:,:,1]>55)|(hsv[:,:,2]>205)|(hsv[:,:,2]<25)]=False;v=cv2.erode(v.astype(np.uint8),np.ones((3,3),np.uint8));small=cv2.resize(gray[57:273,37:253],(96,96),interpolation=cv2.INTER_AREA);valid=cv2.resize(v[57:273,37:253],(96,96),interpolation=cv2.INTER_NEAREST).astype(bool);return edge(small),valid
def aux(qe,qmask,j):
 best=None
 for e,m in refwarp[j]:
  v=qmask&m;count=int(v.sum())
  if count<.3*static_count:continue
  a=qe[v].astype(np.float64);b=e[v].astype(np.float64);a-=a.mean();b-=b.mean();sa=float(np.sqrt(np.mean(a*a)));sb=float(np.sqrt(np.mean(b*b)))
  if min(sa,sb)<.02:continue
  n=float(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)),-1,1));best=n if best is None else max(best,n)
 return best
intent={'mode':'one PTS-paced recording, producer presents latest frame in one overwrite slot, consumer no backlog, zero actuator authority','pacing':'scheduled from original relative_ticks_90k; received_at is real monotonic presentation after source decode; now is monotonic after all processing','ranking':'same frozen DCT top8 + RootSIFT F geometry and minimap masked ZNCC; PTS only used for exclusion and posthoc proxy','fusion':'world**.7 * max(0,(NCC+1)/2)**.3 when aux valid, otherwise neutral','beam':'actual CausalSequenceBeam defaults, real presentation timestamp and postcompute now','no_independent_repeat':True,'no_actions':True};(root/'intent.json').write_text(json.dumps(intent,indent=2));cond=threading.Condition();shared={'slot':None,'finished':False,'produced':0,'dropped':0,'error':None,'first_presentation':None,'last_presentation':None,'late_schedule_max':0.};stop=threading.Event()
def producer():
 try:
  wall_start=None
  for row,frame in decoded_browser(capturedata):
   if stop.is_set():break
   bgr=frame.to_ndarray(format='bgr24');
   if wall_start is None:wall_start=time.monotonic()
   scheduled=wall_start+row['relative_ticks_90k']/90000.;delay=scheduled-time.monotonic()
   if delay>0 and stop.wait(delay):break
   present=time.monotonic()
   with cond:
    if shared['slot'] is not None:shared['dropped']+=1
    shared['slot']=(row['index'],row['relative_ticks_90k'],present,bgr);shared['produced']+=1;shared['first_presentation']=shared['first_presentation'] or present;shared['last_presentation']=present;shared['late_schedule_max']=max(shared['late_schedule_max'],present-scheduled);cond.notify()
 except Exception as e:
  with cond:shared['error']=repr(e)
 finally:
  with cond:shared['finished']=True;cond.notify_all()
thread=threading.Thread(target=producer,daemon=True);thread.start();rows=[];logpath=root/'frames.jsonl';logbytes=0
with logpath.open('w',encoding='utf-8') as log:
 while True:
  with cond:
   while shared['slot'] is None and not shared['finished']:cond.wait(.5)
   if shared['slot'] is None and shared['finished']:break
   index,source_tick,received,bgr=shared['slot'];shared['slot']=None
  begin=time.monotonic();timing={};t=time.monotonic();digest=hashlib.sha256(bgr.tobytes()).hexdigest();gray=cv2.resize(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY),(960,540),interpolation=cv2.INTER_AREA);qp,qd=extract(gray);timing['extract_ms']=(time.monotonic()-t)*1000;t=time.monotonic();v=coarse(gray);dist=np.linalg.norm(refcoarse-v,axis=1);excluded=np.abs(ticks-source_tick)<=13500;dist[excluded]=np.inf;top=np.argsort(dist,kind='stable')[:8];timing['coarse_ms']=(time.monotonic()-t)*1000;t=time.monotonic();scores=np.zeros(169,np.float32);checked=np.zeros(169,bool)
  for j in top:
   j=int(j);checked[j]=True;rd=refdesc[j];rp=refpt[j]
   if len(qd)<2 or len(rd)<2:continue
   knn=bf.knnMatch(qd,rd,k=2);good=[pair[0] for pair in knn if len(pair)==2 and pair[0].distance<.75*pair[1].distance];unique={}
   for z in good:
    if z.trainIdx not in unique or z.distance<unique[z.trainIdx].distance:unique[z.trainIdx]=z
   good=list(unique.values())
   if len(good)<20:continue
   qxy=np.float32([qp[z.queryIdx] for z in good]);rxy=np.float32([rp[z.trainIdx] for z in good]);cv2.setRNGSeed(17);F,im=cv2.findFundamentalMat(qxy,rxy,cv2.FM_RANSAC,1.5,.999,2000)
   if F is not None and im is not None:
    flags=im.ravel().astype(bool);n=int(flags.sum());frac=n/len(good);accepted=qxy[flags];cells=np.floor(accepted/[960,540]*4).astype(int);occupied=len(np.unique(cells[:,1]*4+cells[:,0])) if n else 0
    if n>=20 and frac>=.35 and occupied>=4:scores[j]=min(n/80.,1.)*frac*min((occupied/16.)/.35,1.)
  timing['world_verify_ms']=(time.monotonic()-t)*1000;t=time.monotonic();qe,qm=minimap(bgr);fused=scores.copy();validaux=0
  for j in top:
   n=aux(qe,qm,int(j))
   if n is not None:validaux+=1;fused[j]=(scores[j]**.7)*(max(0,(n+1)/2)**.3)
  timing['minimap_ms']=(time.monotonic()-t)*1000;t=time.monotonic();now=time.monotonic();evidence=beam.update(fused.astype(float).tolist(),source_sequence=int(index),received_at=received,source_sha256=digest,now=now,checked=checked.tolist());timing['filter_ms']=(time.monotonic()-t)*1000;end=time.monotonic();selected=int(indices[evidence.index]) if evidence.index is not None else None;delta=abs(int(ticks[evidence.index])-source_tick)/90000. if evidence.index is not None else None;row={'source_index':int(index),'source_tick_90k':int(source_tick),'present_monotonic':received,'begin_monotonic':begin,'decision_monotonic':now,'analysis_latency_ms':(end-begin)*1000,'frame_age_at_decision_ms':(now-received)*1000,'status':evidence.status,'reason':evidence.reason,'selected_reference_index':selected,'checked_count':int(checked.sum()),'valid_aux_count':validaux,'max_world_score':float(scores.max()),'max_fused_score':float(fused.max()),'time_proxy_error_s':delta,'timing':timing,'execution_qualified':False};line=json.dumps(row,separators=(',',':'))+'\n';logbytes+=len(line.encode());
  if logbytes>500000:stop.set();raise RuntimeError('jsonl_500k_quota')
  log.write(line);log.flush();rows.append(row)
  if len(rows)%50==0:print('processed',len(rows),'source',index,'age_ms',round(row['frame_age_at_decision_ms']),flush=True)
thread.join(5);assert not thread.is_alive() and shared['error'] is None,(thread.is_alive(),shared['error']);assert rows
def pct(key,p):return float(np.percentile([r[key] for r in rows],p))
known=[r for r in rows if r['selected_reference_index'] is not None];summary={'produced':shared['produced'],'processed':len(rows),'overwritten_dropped':shared['dropped'],'first_source_index':rows[0]['source_index'],'last_source_index':rows[-1]['source_index'],'producer_first_to_last_seconds':shared['last_presentation']-shared['first_presentation'],'maximum_presentation_lateness_s':shared['late_schedule_max'],'analysis_latency_ms':{'p50':pct('analysis_latency_ms',50),'p95':pct('analysis_latency_ms',95),'max':pct('analysis_latency_ms',100)},'age_at_decision_ms':{'p50':pct('frame_age_at_decision_ms',50),'p95':pct('frame_age_at_decision_ms',95),'max':pct('frame_age_at_decision_ms',100)},'status_counts':{s:sum(r['status']==s for r in rows) for s in ('reference_selected','unknown','ambiguous','stale')},'fresh_at_decision_250ms':sum(r['frame_age_at_decision_ms']<=250 for r in rows),'selected':len(known),'selected_time_proxy_hit_0_6s':sum(r['time_proxy_error_s']<=.6 for r in known),'selected_time_proxy_wrong_over_2s':sum(r['time_proxy_error_s']>2 for r in known),'denominator_all_processed':len(rows),'mean_phase_ms':{key:float(np.mean([r['timing'][key] for r in rows])) for key in ('extract_ms','coarse_ms','world_verify_ms','minimap_ms','filter_ms')},'jsonl_bytes':logbytes,'source_same_video_time_proxy_only':True,'open_loop_no_environment_response':True,'execution_qualified':False,'physical_actions':0};(root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
