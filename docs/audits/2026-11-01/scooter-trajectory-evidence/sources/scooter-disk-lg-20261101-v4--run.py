"""Bounded single GPU phase: two-frame smoke then 166 DISK/LG features and matches."""
import os,sys,time,json,hashlib,threading,importlib.util,sqlite3,collections,traceback
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='4'
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.pilot.resource_guard import windows_memory
OUT=Path(__file__).resolve().parent;PREP=ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/prepared'
MODELS=ROOT/'.local-pilot/reconstruction-tools/disk-models-20261101'
MASK=ROOT/'.local-pilot/scooter-precise-hud-20261101/mask.png'
intent=json.loads((OUT/'intent.json').read_text('utf-8'));weights=json.loads((OUT/'weights.json').read_text('utf-8'))
started=time.monotonic();gpu_started=None;gpu_admitted=False;minimum_gpu_free=2**63;done=threading.Event();stage='imports';completed=0;minimum_ram=2**63;minimum_commit=2**63
def write(name,obj):
 p=OUT/name;t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def check():
 global minimum_ram,minimum_commit,minimum_gpu_free
 m=windows_memory();minimum_ram=min(minimum_ram,m['availableRamBytes']);minimum_commit=min(minimum_commit,m['commitLimitBytes']-m['committedBytes'])
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*2**30:raise RuntimeError('host_reserve_4_5GiB')
 if gpu_started is not None and time.monotonic()-started>240:raise RuntimeError('v4_total_240s_limit')
 if gpu_admitted:
  free,_=torch.cuda.mem_get_info();minimum_gpu_free=min(minimum_gpu_free,free)
  if free<4*2**30:raise RuntimeError('v4_gpu_free_reserve_4GiB')
 return m
initial=check()
if initial['availableRamBytes']<8*2**30 or initial['commitLimitBytes']-initial['committedBytes']<8*2**30:raise RuntimeError('v4_host_admission_8GiB_RAM_8GiB_commit')
def watch():
 while not done.wait(.25):
  try:check()
  except Exception as exc:
   write('refusal.json',dict(status='resource_refused',reason=str(exc),stage=stage,completed=completed,seconds=time.monotonic()-started,minimum_ram_bytes=minimum_ram,minimum_commit_headroom_bytes=minimum_commit,physicalActions=0));print('RESOURCE_REFUSED '+str(exc),flush=True);os._exit(4)
threading.Thread(target=watch,daemon=True).start()
try:
 import numpy as np
 import torch
 import kornia
 from PIL import Image
 if torch.__version__!='2.9.1+rocm7.2.1' or kornia.__version__!='0.8.2':raise RuntimeError('runtime_changed')
 torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.manual_seed(17)
 if not torch.cuda.is_available():raise RuntimeError('gpu_unavailable')
 gpu_started=time.monotonic();props=torch.cuda.get_device_properties(0);free,total=torch.cuda.mem_get_info()
 if free<11*2**30:raise RuntimeError('v4_gpu_admission_free_11GiB')
 gpu_admitted=True;torch.cuda.set_per_process_memory_fraction(min(1.,8*2**30/props.total_memory));torch.cuda.reset_peak_memory_stats()
 write('gpu-admission.json',dict(free_bytes=free,total_bytes=total,device=props.name,torch_cap_GiB=8,runtime_free_reserve_GiB=4,host_memory=windows_memory()))
 # Refuse every automatic model download path in this process.
 torch.hub.load_state_dict_from_url=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('automatic_download_forbidden'))
 for asset in weights['assets']:
  p=MODELS/asset['file']
  if p.stat().st_size!=asset['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=asset['sha256']:raise RuntimeError('weights_changed')
 stage='load_DISK'
 extractor=kornia.feature.DISK().eval();state=torch.load(MODELS/'depth-save.pth',map_location='cpu',weights_only=True);extractor.load_state_dict(state['extractor'],strict=True);del state;extractor=extractor.to('cuda')
 source=ROOT/'.local-pilot/reconstruction-tools/lightglue/lightglue/lightglue.py'
 if hashlib.sha256(source.read_bytes()).hexdigest()!='77891cc7ff79aea7b03f310288d12549db6704f4a1ec42b0b3364527e31f6546':raise RuntimeError('matcher_source_changed')
 spec=importlib.util.spec_from_file_location('_sphere_disk_lightglue',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 matcher=module.LightGlue(features=None,input_dim=128,add_scale_ori=False,flash=False,mp=False,filter_threshold=.2).eval()
 state=torch.load(MODELS/'disk_lightglue.pth',map_location='cpu',weights_only=True)
 for i in range(9):state={k.replace(f'self_attn.{i}',f'transformers.{i}.self_attn').replace(f'cross_attn.{i}',f'transformers.{i}.cross_attn'):v for k,v in state.items()}
 # The release predates removal of the unused assignment .r parameter. The
 # pinned upstream silently ignores these via strict=False. Allow only this
 # exact obsolete-key set, then retain strict checking for every used tensor.
 legacy={f'log_assignment.{i}.r' for i in range(9)}
 if set(state)-set(matcher.state_dict())!=legacy:raise RuntimeError('unexpected_checkpoint_compatibility')
 compatibility=[]
 for key in sorted(legacy):
  value=state.pop(key)
  if not isinstance(value,torch.Tensor) or not torch.isfinite(value).all():raise RuntimeError('invalid_obsolete_tensor')
  compatibility.append(dict(key=key,shape=list(value.shape)))
 write('checkpoint-compatibility.json',dict(ignored_obsolete_parameters=compatibility,reason='pinned MatchAssignment does not define or use r; exact allowlist only',remaining_state_strict=True,weights_only=True,previous_profile_unchanged=True,new_profile='v4'))
 state.setdefault('confidence_thresholds',matcher.confidence_thresholds);matcher.load_state_dict(state,strict=True);del state;matcher=matcher.to('cuda')
 mask=np.asarray(Image.open(MASK).convert('L')).copy();mask[int(mask.shape[0]*.975):]=0
 if hashlib.sha256(MASK.read_bytes()).hexdigest()!=intent['mask_sha256'] or mask.shape!=(1080,1920):raise RuntimeError('mask_changed')
 rows=json.loads((OUT/'prepared.json').read_text('utf-8'))['images'];metadata={Path(r['image']).name:r for r in intent['source_images']}
 sparse=OUT/'features';sparse.mkdir(exist_ok=False);cache_bytes=0;counts=[];pairs=[];raw_counts=[];audit=[]
 db=sqlite3.connect(OUT/'features.db')
 @torch.inference_mode()
 def extract(row):
  global cache_bytes
  image_id,name,_=row;path=PREP/'images'/name;body=path.read_bytes()
  if hashlib.sha256(body).hexdigest()!=metadata[name]['png_sha256']:raise RuntimeError('png_changed')
  rgb=np.asarray(Image.open(path).convert('RGB')).copy();image=torch.from_numpy(rgb).permute(2,0,1).float().div_(255)[None].to('cuda')
  image=kornia.geometry.transform.resize(image,1024,side='long',antialias=True,align_corners=None)
  scale=np.array([image.shape[-1]/1920,image.shape[-2]/1080],np.float32)
  features=extractor(image,n=None,window_size=5,score_threshold=0.,pad_if_not_divisible=True)[0]
  xy=(features.keypoints.cpu().numpy()+.5)/scale-.5;scores=features.detection_scores.cpu().numpy();desc=features.descriptors.cpu().numpy()
  if not np.isfinite(xy).all() or not np.isfinite(scores).all() or not np.isfinite(desc).all():raise RuntimeError('nonfinite_features')
  ix=np.floor(xy[:,0]+.5).astype(int);iy=np.floor(xy[:,1]+.5).astype(int);inside=(ix>=0)&(ix<1920)&(iy>=0)&(iy<1080)
  allowed=np.flatnonzero(inside);allowed=allowed[mask[iy[allowed],ix[allowed]]>0];selected=allowed[np.argsort(-scores[allowed],kind='stable')[:1024]]
  if len(selected)<15:raise RuntimeError('insufficient_world_candidates')
  xy=np.ascontiguousarray(xy[selected],dtype='<f4');desc=np.ascontiguousarray(desc[selected],dtype='<f4');scores=np.ascontiguousarray(scores[selected],dtype='<f4')
  target=sparse/f'{image_id}.npz';np.savez(target,keypoints=xy,descriptors=desc,keypoint_scores=scores,image_size=np.array([1920,1080],np.float32));cache_bytes+=target.stat().st_size
  if cache_bytes>128*2**20:raise RuntimeError('sparse_cache_128MiB')
  db.execute('INSERT INTO keypoints(image_id,rows,cols,data) VALUES(?,?,?,?)',(image_id,len(xy),2,(xy+.5).astype('<f4').tobytes()));db.commit()
  counts.append(dict(image_id=image_id,name=name,source_index=metadata[name]['source_index'],ticks_90k=metadata[name]['relative_ticks_90k'],detected=len(features.keypoints),mask_eligible=len(allowed),retained=len(xy),png_sha256=metadata[name]['png_sha256']))
  del features,image,rgb,desc,xy,scores
  torch.cuda.synchronize();check()
 lru=collections.OrderedDict()
 def load(row):
  image_id=row[0]
  if image_id in lru:lru.move_to_end(image_id);return lru[image_id]
  with np.load(sparse/f'{image_id}.npz') as data:feats={k:torch.from_numpy(data[k].copy())[None].to('cuda') for k in data.files}
  lru[image_id]=feats
  while len(lru)>2:lru.popitem(last=False)
  return feats
 @torch.inference_mode()
 def match(first,second,*,smoke=False):
  f0,f1=load(first),load(second);result=matcher(dict(image0=f0,image1=f1));matches=result['matches'][0].cpu().numpy()
  if matches.ndim!=2 or matches.shape[1]!=2 or not np.issubdtype(matches.dtype,np.integer) or len(matches)>1024 or (len(matches) and (matches.min()<0 or matches[:,0].max()>=f0['keypoints'].shape[1] or matches[:,1].max()>=f1['keypoints'].shape[1])):raise RuntimeError('matches_invalid')
  if len(matches) and (len(np.unique(matches[:,0]))!=len(matches) or len(np.unique(matches[:,1]))!=len(matches)):raise RuntimeError('matches_not_unique')
  if not torch.isfinite(result['matching_scores0']).all():raise RuntimeError('scores_nonfinite')
  a,b=first[0],second[0];pairs.append(first[1]+' '+second[1]);raw_counts.append(len(matches));m=matches.astype('<u4') if a<b else matches[:,::-1].astype('<u4');pair=min(a,b)*2147483647+max(a,b)
  db.execute('INSERT INTO matches(pair_id,rows,cols,data) VALUES(?,?,?,?)',(pair,len(m),2,m.tobytes()));db.commit()
  if len(matches):
   x=f0['keypoints'][0,matches[:,0]].cpu().numpy();y=f1['keypoints'][0,matches[:,1]].cpu().numpy();audit.append(dict(first=first[1],second=second[1],matches=len(matches),median_displacement_pixels=float(np.median(np.linalg.norm(y-x,axis=1)))))
  torch.cuda.synchronize();check()
 stage='smoke_extract'
 for row in rows[:2]:extract(row)
 stage='smoke_match';match(rows[0],rows[1],smoke=True)
 write('smoke.json',dict(status='passed',images=counts,raw_matches=raw_counts[0],gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved(),gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(),seconds=time.monotonic()-gpu_started,torch=torch.__version__,kornia=kornia.__version__,device=props.name,source_modified=False))
 print('SMOKE_PASS '+json.dumps(dict(raw_matches=raw_counts[0],seconds=time.monotonic()-gpu_started)),flush=True)
 stage='extract'
 for i,row in enumerate(rows[2:],start=3):
  extract(row);completed=i
  if i%10==0 or i==len(rows):write('progress.json',dict(stage=stage,completed=i,total=166,seconds=time.monotonic()-gpu_started,peak_gpu_reserved=torch.cuda.max_memory_reserved(),cache_bytes=cache_bytes));print(f'extract {i}/166 seconds={time.monotonic()-gpu_started:.1f}',flush=True)
 del extractor;torch.cuda.empty_cache();stage='match';completed=1
 wanted=sum(i+lag<len(rows) for i in range(len(rows)) for lag in (1,2,3,5,8))
 for i,first in enumerate(rows):
  for lag in (1,2,3,5,8):
   if i+lag>=len(rows) or (i==0 and lag==1):continue
   match(first,rows[i+lag]);completed+=1
   if completed%25==0 or completed==wanted:write('progress.json',dict(stage=stage,completed=completed,total=wanted,seconds=time.monotonic()-gpu_started,peak_gpu_reserved=torch.cuda.max_memory_reserved()));print(f'match {completed}/{wanted} seconds={time.monotonic()-gpu_started:.1f}',flush=True)
 (OUT/'pairs.txt').write_text('\n'.join(pairs)+'\n',encoding='ascii')
 report=dict(status='features_and_raw_matches_complete',method='DISK_depth_LightGlue_disk',source_manifest_sha256=intent['source_manifest_sha256'],images=counts,pairs=wanted,total_keypoints=sum(c['retained'] for c in counts),raw_matches=dict(min=int(min(raw_counts)),median=float(np.median(raw_counts)),max=int(max(raw_counts)),total=int(sum(raw_counts))),pair_audit=audit,source_input_sha256=intent['source_input_sha256'],mask_sha256=intent['mask_sha256'],resize=[1024,576],quota_after_mask=1024,mask_footer=.025,keypoints_cols=2,descriptors_in_database=0,descriptors_labelled_SIFT=False,sparse_cache_bytes=cache_bytes,sparse_cache_LRU=2,lightglue_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),torch=torch.__version__,kornia=kornia.__version__,flash=False,mp=False,peak_gpu_reserved_bytes=torch.cuda.max_memory_reserved(),peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(),gpu_seconds=time.monotonic()-gpu_started,minimum_available_ram_bytes=minimum_ram,minimum_commit_headroom_bytes=minimum_commit,minimum_gpu_free_bytes=minimum_gpu_free,new_authorized_profile='v4',torch_gpu_cap_GiB=8,host_admission_RAM_GiB=8,host_admission_commit_GiB=8,gpu_admission_free_GiB=11,gpu_runtime_reserve_GiB=4,master_transcoded=False,comparison='practical pipelines, not single-factor A/B',geometric_verification_complete=False,independent_pose_holdout=False,executionQualified=False,physicalActions=0)
 lru.clear();del matcher;torch.cuda.empty_cache();db.close();write('features.json',report)
 print('COMPLETE '+json.dumps({k:report[k] for k in ('pairs','total_keypoints','raw_matches','gpu_seconds','peak_gpu_reserved_bytes')}),flush=True)
except Exception as exc:
 write('failure.json',dict(status='failed',error=type(exc).__name__,reason=str(exc),stage=stage,completed=completed,seconds=time.monotonic()-started,traceback=traceback.format_exc(),source_modified=False,physicalActions=0));print('FAILED '+type(exc).__name__+' '+str(exc),flush=True);raise
finally:done.set()
