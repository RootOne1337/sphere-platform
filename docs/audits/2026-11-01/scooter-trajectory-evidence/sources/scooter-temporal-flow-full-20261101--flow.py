"""Single bounded full-807-edge temporal consistency candidate, no geometry solve.

Retains original SIFT feature IDs; new raw matches are a filtered subset of
original verified LG inliers. Old geometries are cleared, not silently reused.
Pointwise LK is batched by source endpoint; the narrow protocol is unchanged.
"""
import os,sys,time,json,hashlib,sqlite3,subprocess,ctypes,collections
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='2';os.environ['MKL_NUM_THREADS']='1'
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
from scripts.pilot.resource_guard import windows_memory
PREP=ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/prepared';DB=PREP.parent/'database.db';CAPTURE=ROOT/'.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input';MASK=ROOT/'.local-pilot/scooter-precise-hud-20261101/mask.png';NARROW=ROOT/'.local-pilot/scooter-temporal-flow-20261101'
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def memory():
 m=windows_memory()
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*2**30:raise RuntimeError('runtime_host_4_5GiB')
 return m
def snapshot():
 paths=[DB,PREP/'reconstruction-input.json',MASK,NARROW/'probe.py',NARROW/'report.json',ROOT/'scripts/pilot/video_observations.py',*[CAPTURE/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]]
 prepared=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'))
 for row in prepared['images']:
  p=PREP/row['image']
  if sha(p)!=row['png_sha256']:raise RuntimeError('source_PNG_changed')
  paths.append(p)
 return {str(p.relative_to(ROOT)):sha(p) for p in paths}
def affinity():
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();a=ctypes.c_size_t();b=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(a),ctypes.byref(b));bits=[1<<i for i in range(64) if a.value&(1<<i)];assert k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:2])))
def logical_features(db):
 result={}
 for table in ('keypoints','descriptors'):
  h=hashlib.sha256()
  for row in db.execute('SELECT * FROM '+table+' ORDER BY image_id'):
   for value in row:
    data=value if isinstance(value,bytes) else str(value).encode();h.update(len(data).to_bytes(8,'little'));h.update(data)
  result[table]=h.hexdigest()
 return result
def worker():
 if os.environ.get('SPHERE_TEMPORAL_CHILD')!=str(os.getppid()):raise RuntimeError('owned_parent_required')
 affinity();memory();import numpy as np,cv2,av
 from PIL import Image
 from motor_worker.browser_teach import validate_browser,decoded_browser
 from scripts.pilot.video_observations import track_source_points
 cv2.setNumThreads(2);began=time.monotonic();capture=validate_browser(CAPTURE);prepared=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'));meta={Path(r['image']).name:r for r in prepared['images']};assert len(capture.frames)==901 and capture.geometry==(1920,1080)
 mask=cv2.imread(str(MASK),0);mask[int(1080*.975):]=0;scale=np.array([.5,.5],np.float32)
 def to_cv(kp):return (kp*scale-.5).astype(np.float32)
 def to_colmap(q):return (q+.5)/scale
 def allowed(kp):
  pix=np.floor(kp).astype(int);inside=np.isfinite(kp).all(1)&(pix[:,0]>=0)&(pix[:,0]<1920)&(pix[:,1]>=0)&(pix[:,1]<1080);answer=np.zeros(len(kp),bool);sel=np.flatnonzero(inside);answer[sel]=mask[pix[sel,1],pix[sel,0]]>0;return answer
 with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as source:
  names=dict(source.execute('SELECT image_id,name FROM images'));xy={i:np.frombuffer(blob,dtype='<f4').reshape(n,c)[:,:2].copy() for i,n,c,blob in source.execute('SELECT image_id,rows,cols,data FROM keypoints')};feature_hashes=logical_features(source);edges=[]
  for pid,n,col,data in source.execute('SELECT pair_id,rows,cols,data FROM two_view_geometries WHERE rows>0 ORDER BY pair_id'):
   i,j=divmod(pid,2147483647);a=int(names[i][:-4]);b=int(names[j][:-4]);matches=np.frombuffer(data,dtype='<u4').reshape(n,col).copy()
   if a>b:a,b=b,a;i,j=j,i;matches=matches[:,::-1].copy()
   edges.append(dict(pid=pid,a=a,b=b,ia=i,ib=j,matches=matches))
 assert len(edges)==807 and len(names)==166
 grays=np.empty((901,540,960),np.uint8)
 if grays.nbytes>512*2**20:raise RuntimeError('decoded_gray_cache_512MiB')
 ticks=np.array([r['relative_ticks_90k'] for r in capture.frames],np.int64);decoded=0;pixel_verified=[]
 for row,frame in decoded_browser(capture):
  index=row['index'];rgb=frame.to_ndarray(format='rgb24');grays[index]=cv2.cvtColor(cv2.resize(rgb,(960,540),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY);decoded+=1
  name=f'{index:08d}.png'
  if name in meta:
   if row['relative_ticks_90k']!=meta[name]['relative_ticks_90k'] or not np.array_equal(rgb,np.asarray(Image.open(PREP/'images'/name).convert('RGB'))):raise RuntimeError('selected_PNG_RGB_or_PTS_binding')
   pixel_verified.append(index)
  if decoded%100==0:memory();write('flow-progress.json',dict(stage='single_decode',completed=decoded,total=901,seconds=time.monotonic()-began))
 assert decoded==901 and len(pixel_verified)==166
 forward={};backward={}
 # Batching independent point trajectories is an optimization only. A point
 # never survives a failed hop and never receives a fabricated observation.
 for direction,results in ((1,forward),(-1,backward)):
  groups=collections.defaultdict(list)
  for e in edges:groups[e['a'] if direction==1 else e['b']].append(e)
  for num,(anchor,group) in enumerate(sorted(groups.items())):
   col=0 if direction==1 else 1;image_id=group[0]['ia'] if direction==1 else group[0]['ib'];feature_ids=np.unique(np.concatenate([e['matches'][:,col] for e in group]));lookup=np.full(len(xy[image_id]),-1,int);lookup[feature_ids]=np.arange(len(feature_ids));points=to_cv(xy[image_id][feature_ids]);valid=allowed(xy[image_id][feature_ids]);last=np.full(len(feature_ids),-1 if direction==1 else 10000,int);targets=collections.defaultdict(list)
   for e in group:
    target=e['b'] if direction==1 else e['a'];local=lookup[e['matches'][:,col]];last[local]=np.maximum(last[local],target) if direction==1 else np.minimum(last[local],target);targets[target].append((e,local))
   far=int(last.max() if direction==1 else last.min());previous=anchor
   for current in range(anchor+direction,far+direction,direction):
    selected=np.flatnonzero(valid&((last>=current) if direction==1 else (last<=current)))
    if abs(ticks[current]-ticks[previous])>22500:valid[:]=False
    elif len(selected):
     moved,good=track_source_points(grays[previous],grays[current],points[selected],tolerance=.75,window=21,levels=3);good&=np.isfinite(moved).all(1)&(moved[:,0]>=0)&(moved[:,0]<960)&(moved[:,1]>=0)&(moved[:,1]<540);points[selected]=moved;valid[selected[~good]]=False
    for e,local in targets.get(current,[]):results[e['pid']]=(points[local].copy(),valid[local].copy())
    previous=current
   if num%10==0:memory();write('flow-progress.json',dict(stage='forward' if direction==1 else 'backward',completed=num+1,total=len(groups),seconds=time.monotonic()-began));print(('forward' if direction==1 else 'backward')+f' {num+1}/{len(groups)} {time.monotonic()-began:.1f}s',flush=True)
 # Full-cycle seeds are the measured forward endpoints, not the LG target.
 filtered={};reports=[];narrow_report=json.loads((NARROW/'report.json').read_text('utf-8'));narrow_pairs={tuple(r['pair']) for r in narrow_report['pairs']};selftests=[];flow_arrays=OUT/'edge-flow-evidence';flow_arrays.mkdir(exist_ok=False)
 for index,e in enumerate(edges):
  a,b=e['a'],e['b'];m=e['matches'];pa=xy[e['ia']][m[:,0]];pb=xy[e['ib']][m[:,1]];f,fv=forward[e['pid']];back,bv=backward[e['pid']];fe=np.linalg.norm(to_colmap(f)-pb,axis=1);be=np.linalg.norm(to_colmap(back)-pa,axis=1);base=fv&bv&allowed(pa)&allowed(pb)&(fe<=3)&(be<=3)&allowed(to_colmap(f))&allowed(to_colmap(back));selected=np.flatnonzero(base);cycle_error=np.full(len(m),np.inf,np.float32);cycle_valid=np.zeros(len(m),bool)
  if len(selected):
   points=f[selected].copy();valid=np.ones(len(selected),bool)
   for current in range(b-1,a-1,-1):
    live=np.flatnonzero(valid)
    if abs(ticks[current+1]-ticks[current])>22500:valid[:]=False;break
    if not len(live):break
    moved,good=track_source_points(grays[current+1],grays[current],points[live],tolerance=.75,window=21,levels=3);good&=np.isfinite(moved).all(1)&(moved[:,0]>=0)&(moved[:,0]<960)&(moved[:,1]>=0)&(moved[:,1]<540);points[live]=moved;valid[live[~good]]=False
   cycle_error[selected]=np.linalg.norm(to_colmap(points)-pa[selected],axis=1);cycle_valid[selected]=valid
  keep=base&cycle_valid&(cycle_error<=1.5);retained=m[keep].copy();candidate_count=len(retained)
  if len(retained)<15:retained=np.empty((0,2),np.uint32)
  filtered[e['pid']]=retained if e['ia']<e['ib'] else retained[:,::-1].copy()
  np.savez(flow_arrays/f'{a}-{b}.npz',source_inlier_indices=np.flatnonzero(keep).astype(np.uint32),forward_endpoint_error_px=fe,backward_endpoint_error_px=be,full_cycle_error_px=cycle_error,per_hop_forward_valid=fv,per_hop_backward_valid=bv,strict_keep=keep)
  record=dict(pair=[a,b],pair_id=e['pid'],PTS=[int(ticks[a]),int(ticks[b])],source_frame_gap=b-a,original_verified=len(m),forward_valid=int(fv.sum()),backward_valid=int(bv.sum()),both_endpoint_le3=int(base.sum()),full_cycle_le1_5=candidate_count,new_raw_rows=len(retained));reports.append(record)
  if (a,b) in narrow_pairs:
   with np.load(NARROW/f'pair-{a}-{b}.npz',allow_pickle=False) as old:equal=np.array_equal(keep,old['additional_full_cycle_consistent'])
   selftests.append(dict(pair=[a,b],exact_narrow_strict_mask_equal=equal))
  if index%40==0:memory();write('flow-progress.json',dict(stage='full_cycles',completed=index+1,total=807,seconds=time.monotonic()-began));print(f'cycle {index+1}/807 {time.monotonic()-began:.1f}s',flush=True)
 if len(selftests)!=8 or not all(r['exact_narrow_strict_mask_equal'] for r in selftests):write('narrow-reproduction-refusal.json',dict(selftests=selftests));raise RuntimeError('batching_did_not_exactly_reproduce_narrow_protocol')
 parents={i:i for i in names}
 def find(x):
  while parents[x]!=x:parents[x]=parents[parents[x]];x=parents[x]
  return x
 for pid,m in filtered.items():
  if len(m):i,j=divmod(pid,2147483647);parents[find(i)]=find(j)
 components=collections.Counter(find(i) for i in names);sizes=sorted(components.values(),reverse=True)
 with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(OUT/'filtered-verified-as-new-raw.db') as target:
  source.backup(target);target.execute('DELETE FROM matches');target.execute('DELETE FROM two_view_geometries')
  for pid,m in filtered.items():target.execute('INSERT INTO matches(pair_id,rows,cols,data) VALUES(?,?,?,?)',(pid,len(m),2,m.astype('<u4').tobytes()))
  target.commit()
  if logical_features(target)!=feature_hashes:raise RuntimeError('SIFT_feature_tables_changed')
  assert target.execute('SELECT COUNT(*) FROM two_view_geometries').fetchone()[0]==0 and target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 pairlines=[]
 for pid,m in filtered.items():
  if len(m):i,j=divmod(pid,2147483647);pairlines.append(names[i]+' '+names[j])
 (OUT/'pairs-to-reverify.txt').write_text('\n'.join(pairlines)+'\n',encoding='ascii')
 report=dict(status='full_flow_graph_ready_for_reverification' if sizes==[166] else 'temporal_graph_disconnected_do_not_start_mapping',original_verified_edges=807,new_raw_definition='Original verified LG inliers retained only when fixed narrow temporal checks pass; this is NOT preserved original raw descriptor matching.',retained_nonempty_edges=len(pairlines),empty_edges=807-len(pairlines),retained_matches=sum(len(m) for m in filtered.values()),original_verified_matches=sum(len(e['matches']) for e in edges),components=sizes,all_166_connected=sizes==[166],flow_protocol=dict(analysis=[960,540],SIFT_features_preserved_without_1024_cap=True,per_hop_FB_source_px=1.5,both_endpoint_source_px=3,full_cycle_source_px=1.5,mask='binary precise mask + bottom2.5%, endpoints only',small_hop_gap_limit_ms=250,window=21,pyramid_levels=3,coordinate='COLMAP*scale-.5; inverse=(OpenCV+.5)/scale',thresholds_unchanged_from_narrow=True,batched_independent_point_trajectories=True),narrow_exact_mask_reproduction=selftests,decoded_all_901_once=True,gray_cache_bytes=grays.nbytes,gray_cache_cap_bytes=512*2**20,all_166_RGB_and_PTS_exact=True,source_manifest_sha256=prepared['source_manifest_sha256'],feature_table_sha256=feature_hashes,source_SIFT_max_keypoints=max(len(x) for x in xy.values()),edge_reports=reports,worker_seconds=time.monotonic()-began,old_geometries_cleared=True,geometries_reverified=False,source_modified=False,GPU_initialized=False,solver_executed=False,independent_ground_truth=False,physicalActions=0)
 write('flow-report.json',report);print('FLOW_DONE '+json.dumps({k:report[k] for k in ('status','retained_nonempty_edges','retained_matches','components','worker_seconds')}),flush=True)
def launch():
 t=time.monotonic();initial=memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6*2**30:write('waiting.json',dict(status='waiting_admission_6GiB',memory=initial));return
 if (OUT/'flow-intent.json').exists():raise RuntimeError('single_full_graph_attempt_already_exists')
 before=snapshot();write('flow-intent.json',dict(scope='one_full807_temporal_candidate',source_hashes=before,hard_seconds=240,preferred_seconds=180,CPU_processors=2,host_admission_GiB=6,runtime_reserve_GiB=4.5,gray_cache_cap_MiB=512,own_DB_only=True,physicalActions=0));env=os.environ.copy();env['SPHERE_TEMPORAL_CHILD']=str(os.getpid());env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'.local-pilot/motor-worker-venv/Lib/site-packages')]);samples=[];reason=None
 with (OUT/'flow-worker.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(Path(sys._base_executable)),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=memory();samples.append(m)
    if time.monotonic()-t>240:raise RuntimeError('hard_wall_240s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 after=snapshot();unchanged=before==after
 if not unchanged:reason='source_hashes_changed'
 write('flow-receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=time.monotonic()-t,source_hashes_unchanged=unchanged,min_available_RAM_GiB=min((m['availableRamBytes'] for m in samples),default=initial['availableRamBytes'])/2**30,min_commit_headroom_GiB=min((m['commitLimitBytes']-m['committedBytes'] for m in samples),default=initial['commitLimitBytes']-initial['committedBytes'])/2**30,CPU_processors=2,owned_direct_base_interpreter=True,GPU_initialized=False,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 print('FULL_TEMPORAL_FLOW_COMPLETE_SOURCE_UNCHANGED',flush=True)
if __name__=='__main__':
 if sys.argv[1:]==['--run']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use --run for the single authorized full temporal candidate.')
