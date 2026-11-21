"""CPU-only SIFT/RootSIFT cache; no torch or matcher imports."""
import os,sys,json,hashlib,time,shutil,traceback
from pathlib import Path
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='')
sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2
from scripts.pilot.resource_guard import windows_memory
cv2.setNumThreads(2)
out=Path('.local-pilot/scooter-stage-isolation-20261101');origin=Path('.local-pilot/zaezd888-diagnosis-20261031/dense-tracks');prepared=Path('.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared');maskpath=Path('.local-pilot/scooter-precise-hud-20261101/mask.png');src=Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');prev=Path('.local-pilot/scooter-pair-stream-20261101/feature-receipt.json');G=1024**3;start=time.monotonic()
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def phase(n):
 m=windows_memory();ram=m['availableRamBytes'];commit=m['commitLimitBytes']-m['committedBytes'];elapsed=time.monotonic()-start
 (out/'stage1-progress.json').write_text(json.dumps({'images':n,'total':163,'elapsed_s':round(elapsed,2),'free_ram':ram,'free_commit':commit}))
 if min(ram,commit)<4.5*G:raise RuntimeError('host_reserve_below_4.5GiB')
 if elapsed>115:raise TimeoutError('stage1_deadline')
try:
 cache=out/'cache';cache.mkdir(exist_ok=False);metadata=json.loads((origin/'reconstruction-input.json').read_text());old=json.loads(prev.read_text());rows=metadata['images']
 if len(rows)!=163 or len(old)!=163:raise RuntimeError('unexpected_source_count')
 inputs=[src/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[origin/'reconstruction-input.json',maskpath,prev];before={str(p):sha(p) for p in inputs}
 if before[str(maskpath)]!='f638c5d6da826eebfae0f3be57784ea4518dfac4238a6bcddaffbfbed0fb1ec7':raise RuntimeError('mask_changed')
 mask=cv2.imread(str(maskpath),0)
 if mask is None or mask.shape!=(1080,1920):raise RuntimeError('mask_invalid')
 mask[int(1080*.975):]=0;sift=cv2.SIFT_create(nfeatures=8192,contrastThreshold=.0066667,edgeThreshold=10)
 result={};total=0
 for i,row in enumerate(sorted(rows,key=lambda r:Path(r['image']).name)):
  name=Path(row['image']).name;p=prepared/'images'/name
  if sha(p)!=row['png_sha256'] or sha(origin/row['image'])!=row['png_sha256']:raise RuntimeError('source_png_mismatch')
  gray=cv2.imread(str(p),cv2.IMREAD_GRAYSCALE);keypoints,desc=sift.detectAndCompute(gray,mask)
  if desc is None or len(keypoints)<15:raise RuntimeError('insufficient_features')
  if len(keypoints)>4096:
   strongest=sorted(range(len(keypoints)),key=lambda k:(-keypoints[k].response,k))[:4096];keypoints=[keypoints[k] for k in strongest];desc=desc[strongest]
  xy=np.asarray([k.pt for k in keypoints],dtype='float32')+.5;scales=np.asarray([k.size for k in keypoints],dtype='float32');angles=np.deg2rad(np.asarray([k.angle for k in keypoints],dtype='float32'))
  desc/=np.maximum(desc.sum(-1,keepdims=True),1e-6);desc=np.sqrt(np.maximum(desc,1e-6));desc/=np.maximum(np.linalg.norm(desc,axis=-1,keepdims=True),1e-6)
  data={'keypoints':xy,'scales':scales,'oris':angles,'descriptors':desc,'image_size':np.array([1920,1080],dtype='float32')};h=hashlib.sha256()
  for k in sorted(data):h.update(k.encode());h.update(data[k].tobytes())
  feature=h.hexdigest()
  if feature!=old[name]['sha256'] or len(keypoints)!=old[name]['count']:raise RuntimeError('prior_feature_hash_mismatch:'+name)
  if total+sum(v.nbytes for v in data.values())+10000>450*2**20 or shutil.disk_usage(cache).free<20*G+3*2**20:raise RuntimeError('cache_disk_limit')
  file=cache/(name+'.npz');np.savez(file,**data);total+=file.stat().st_size
  if total>450*2**20:raise RuntimeError('cache_quota')
  result[name]={'source_index':row['source_index'],'ticks_90k':row['relative_ticks_90k'],'png_sha256':row['png_sha256'],'feature_sha256':feature,'cache_sha256':sha(file),'count':len(keypoints),'bytes':file.stat().st_size};phase(i+1)
 after={str(p):sha(p) for p in inputs}
 if before!=after:raise RuntimeError('source_changed')
 receipt={'status':'complete','images':len(result),'cache_total_bytes':total,'prior_feature_hashes_all_match':True,'source_hashes_before':before,'source_hashes_after':after,'source_unchanged':before==after,'torch_imported':'torch' in sys.modules,'opencv':cv2.__version__,'elapsed_s':time.monotonic()-start,'files':result}
 if receipt['torch_imported']:raise RuntimeError('unexpected_torch_import')
 (out/'stage1-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps({'status':'complete','images':len(result),'cache_bytes':total,'elapsed_s':receipt['elapsed_s']}),flush=True)
except Exception as e:
 m=windows_memory();err={'status':'partial','type':type(e).__name__,'message':str(e)[:500],'elapsed_s':time.monotonic()-start,'free_ram':m['availableRamBytes'],'free_commit':m['commitLimitBytes']-m['committedBytes'],'traceback':[{'file':Path(x.filename).name,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(e.__traceback__)]};(out/'stage1-failure.json').write_text(json.dumps(err,indent=2));print(json.dumps(err),flush=True);raise SystemExit(1)
