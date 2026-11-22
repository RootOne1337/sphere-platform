"""FP32 matcher; read at most two lossless CPU feature files at a time."""
import os,sys,json,hashlib,time,socket,traceback,sqlite3,ctypes
from pathlib import Path
from collections import OrderedDict
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',HF_HUB_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
def deny(*a,**k):raise RuntimeError('network_disabled')
socket.socket.connect=deny;socket.create_connection=deny
sys.path.insert(0,os.getcwd());sys.path.insert(0,str(Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
import numpy as np,torch,pycolmap as p
from scripts.pilot.resource_guard import windows_memory
from scripts.pilot.learned_route_features import load_matcher,validate_assets
torch.set_num_threads(2)
out=Path('.local-pilot/scooter-stage-isolation-20261101');origin=Path('.local-pilot/zaezd888-diagnosis-20261031/dense-tracks');prepared=Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared');G=1024**3;start=time.monotonic();last=0
class Proc(ctypes.Structure):
 _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong),('peak_ws',ctypes.c_size_t),('ws',ctypes.c_size_t),('peak_paged',ctypes.c_size_t),('paged',ctypes.c_size_t),('peak_nonpaged',ctypes.c_size_t),('nonpaged',ctypes.c_size_t),('pagefile',ctypes.c_size_t),('peak_pagefile',ctypes.c_size_t),('private',ctypes.c_size_t)]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def memory():
 m=windows_memory();return m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']
def guard():
 ram,commit=memory()
 if min(ram,commit)<4.5*G:raise RuntimeError(f'host_reserve_below_4.5GiB:ram={ram}:commit={commit}')
 if time.monotonic()-start>405:raise TimeoutError('stage2_deadline_405s')
def phase(stage,n,total,**extra):
 guard();ram,commit=memory();proc=Proc();proc.cb=ctypes.sizeof(proc);ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p;ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Proc),ctypes.c_ulong]
 if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(proc),proc.cb):raise OSError('process_memory_query_failed')
 r={'stage':stage,'completed':n,'total':total,'elapsed_s':round(time.monotonic()-start,3),'free_ram':ram,'free_commit':commit,'private_bytes':proc.private,'working_set_bytes':proc.ws,**extra}
 if torch.cuda.is_initialized():r.update(gpu_allocated=torch.cuda.memory_allocated(),gpu_reserved=torch.cuda.memory_reserved())
 (out/'stage2-progress.json').write_text(json.dumps(r));
 with (out/'stage2-phases.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
 print(json.dumps(r),flush=True)
try:
 if 'cv2' in sys.modules:raise RuntimeError('unexpected_cv2_import')
 receipt=json.loads((out/'stage1-receipt.json').read_text());rows=receipt['files']
 if receipt['status']!='complete' or not receipt['prior_feature_hashes_all_match'] or len(rows)!=163:raise RuntimeError('stage1_not_complete')
 if (out/'database.db').exists():raise RuntimeError('database_already_exists')
 for n,(name,r) in enumerate(sorted(rows.items())):
  if sha(out/'cache'/(name+'.npz'))!=r['cache_sha256'] or sha(prepared/'images'/name)!=r['png_sha256']:raise RuntimeError('feature_or_png_hash_mismatch:'+name)
  guard()
 phase('cache_hashes_verified',163,163)
 dbpath=out/'database.db';p.Database.open(dbpath).close();p.import_images(dbpath,prepared/'images',camera_mode=p.CameraMode.SINGLE,options=p.ImageReaderOptions(camera_model='SIMPLE_PINHOLE'))
 lru=OrderedDict();max_lru=0
 def get(name):
  global max_lru
  if name in lru:lru.move_to_end(name);return lru[name]
  with np.load(out/'cache'/(name+'.npz'),allow_pickle=False) as z:data={k:torch.from_numpy(z[k])[None] for k in z.files}
  lru[name]=data
  if len(lru)>2:lru.popitem(last=False)
  max_lru=max(max_lru,len(lru));return data
 with p.Database.open(dbpath) as db:
  images=sorted(db.read_all_images(),key=lambda x:x.name)
  if len(images)!=163 or {x.name for x in images}!=set(rows):raise RuntimeError('database_image_mismatch')
  for n,im in enumerate(images):
   data=get(im.name);xy=data['keypoints'][0].numpy();scales=data['scales'][0].numpy();angles=data['oris'][0].numpy();desc=data['descriptors'][0].numpy()
   db.write_keypoints(im.image_id,np.column_stack([xy,scales,angles]));db.write_descriptors(im.image_id,p.FeatureDescriptors(p.FeatureExtractorType.SIFT,np.clip(np.round(desc*512),0,255).astype('uint8')))
   if (n+1)%16==0:phase('database_features',n+1,163,lru_images=len(lru))
  lru.clear();del data,xy,scales,angles,desc
  if not torch.cuda.is_available():raise RuntimeError('gpu_unavailable')
  free,total=torch.cuda.mem_get_info();limit=min(3*G,free-2*G)
  if free<5*G or limit<=0:raise RuntimeError('gpu_insufficient')
  matcher=load_matcher(Path.cwd(),memory_fraction=limit/total,device='cuda');torch.set_num_threads(2)
  if matcher.conf.mp:raise RuntimeError('unexpected_mixed_precision')
  if 'cv2' in sys.modules:raise RuntimeError('unexpected_cv2_import')
  phase('model_loaded',0,796,gpu_free_before=free,gpu_total=total,gpu_cap=limit)
  count=0;counts=[];pairs=[];cache_events=[];expected=sum(i+lag<len(images) for i in range(len(images)) for lag in (1,2,3,5,8))
  if expected!=796:raise RuntimeError('pair_count_mismatch')
  with torch.inference_mode():
   for i,first in enumerate(images):
    for lag in (1,2,3,5,8):
     if i+lag>=len(images):continue
     second=images[i+lag];a=get(first.name);b=get(second.name);x={k:v.to('cuda') for k,v in a.items()};y={k:v.to('cuda') for k,v in b.items()}
     result=matcher({'image0':x,'image1':y});matches=result['matches'][0].cpu().numpy().astype('uint32')
     if matches.ndim!=2 or matches.shape[1]!=2 or len(matches)>4096 or len(matches) and (matches[:,0].max()>=a['keypoints'].shape[1] or matches[:,1].max()>=b['keypoints'].shape[1]):raise RuntimeError('invalid_matches')
     db.write_matches(first.image_id,second.image_id,matches);pairs.append(f'{first.name} {second.name}');counts.append(len(matches));count+=1;del result,x,y,a,b;guard()
     if count%16==0:
      if torch.cuda.memory_reserved()>int(1.8*G):
       before=torch.cuda.memory_reserved();torch.cuda.empty_cache();cache_events.append({'pair':count,'before':before,'after':torch.cuda.memory_reserved()})
      phase('matching',count,796,lru_images=len(lru),release_events=len(cache_events))
  if count!=796:raise RuntimeError('pair_count_incomplete')
  gpu={'peak_allocated':torch.cuda.max_memory_allocated(),'peak_reserved':torch.cuda.max_memory_reserved(),'cap':limit,'free_before':free,'total':total,'release_events':cache_events};del matcher;lru.clear();torch.cuda.empty_cache()
 pairfile=out/'learned-pairs.txt';pairfile.write_text('\n'.join(pairs)+'\n',encoding='ascii')
 with sqlite3.connect(f'file:{dbpath.resolve().as_posix()}?mode=ro',uri=True) as db:count_db=db.execute('select count(*) from matches').fetchone()[0]
 if count_db!=796:raise RuntimeError('db_pair_count_incomplete')
 after={k:sha(Path(k)) for k in receipt['source_hashes_before']}
 if after!=receipt['source_hashes_before']:raise RuntimeError('source_hash_changed')
 validate_assets(Path.cwd());phase('matching_complete',796,796)
 result={'status':'matching_complete_not_verified','images':163,'raw_pairs':count_db,'geometric_verification_complete':False,'precision':'fp32','pair_graph_lags':[1,2,3,5,8],'feature_cache':'lossless float32 per image, LRU <=2','max_lru_images':max_lru,'cv2_imported':'cv2' in sys.modules,'stage1_receipt_sha256':sha(out/'stage1-receipt.json'),'pair_file_sha256':sha(pairfile),'database_sha256':sha(dbpath),'source_hashes_after':after,'source_unchanged':True,'gpu':gpu,'elapsed_s':time.monotonic()-start,'limitations':'No verified geometry or mapping yet. Requires separate process and explicit completion before assessing route.'}
 (out/'stage2-receipt.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
except Exception as e:
 ram,commit=memory();err={'status':'partial','type':type(e).__name__,'message':str(e)[:500],'elapsed_s':time.monotonic()-start,'free_ram':ram,'free_commit':commit,'traceback':[{'file':Path(x.filename).name,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(e.__traceback__)]};(out/'stage2-failure.json').write_text(json.dumps(err,indent=2));print(json.dumps(err),flush=True);raise SystemExit(1)
