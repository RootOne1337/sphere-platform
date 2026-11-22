"""Same temporal protocol for only 24 new bridge LG pairs; old807 immutable."""
import os,sys,time,json,sqlite3,subprocess,ctypes,inspect,ast,importlib.util
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='1'
BRIDGE=Path(__file__).resolve().parent;OUT=BRIDGE/'new-flow';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('_original_temporal_algorithm',BRIDGE.parent/'scooter-temporal-flow-full-20261101/flow.py');algorithm=importlib.util.module_from_spec(spec);spec.loader.exec_module(algorithm)
DB=BRIDGE/'features-raw.db';PREP=BRIDGE/'prepared'
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def affinity4():
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];p=k.GetCurrentProcess();a=ctypes.c_size_t();s=ctypes.c_size_t();assert k.GetProcessAffinityMask(p,ctypes.byref(a),ctypes.byref(s));bits=[1<<i for i in range(64) if s.value&(1<<i)];assert k.SetProcessAffinityMask(p,ctypes.c_size_t(sum(bits[:4])))
def old_hashes(path):
 import hashlib
 result={}
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
  for table in ('keypoints','descriptors','matches'):
   h=hashlib.sha256();query='SELECT * FROM '+table+(' WHERE image_id<=166 ORDER BY image_id' if table!='matches' else ' WHERE pair_id/2147483647<=166 AND pair_id%2147483647<=166 ORDER BY pair_id');count=0
   for row in db.execute(query):
    count+=1
    for value in row:
     data=value if isinstance(value,bytes) else str(value).encode();h.update(len(data).to_bytes(8,'little'));h.update(data)
   result[table]=dict(rows=count,sha256=h.hexdigest())
 return result
def snapshot():
 result=algorithm.snapshot();paths=[DB,BRIDGE/'features-receipt.json',BRIDGE/'match-receipt.json',BRIDGE/'feature-match-receipt.json',BRIDGE/'bridge-plan.json',PREP/'reconstruction-input.json']
 metadata=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'))
 for row in metadata['images']:
  p=PREP/row['image']
  if algorithm.sha(p)!=row['png_sha256']:raise RuntimeError('prepared169_PNG_changed')
  paths.append(p)
 for p in paths:result[str(p.relative_to(algorithm.ROOT))]=algorithm.sha(p)
 return result
def generate():
 source=inspect.getsource(algorithm.worker)
 def change(a,b):
  nonlocal source
  if source.count(a)!=1:raise RuntimeError('source_adapter_ambiguous:'+a[:70])
  source=source.replace(a,b)
 change('cv2.setNumThreads(2);began=', 'cv2.setNumThreads(4);began=')
 change('SELECT pair_id,rows,cols,data FROM two_view_geometries WHERE rows>0 ORDER BY pair_id','SELECT pair_id,rows,cols,data FROM matches WHERE rows>0 AND (pair_id/2147483647>166 OR pair_id%2147483647>166) ORDER BY pair_id')
 change('assert len(edges)==807 and len(names)==166','assert len(edges)==24 and len(names)==169')
 change("grays=np.empty((901,540,960),np.uint8)\n if grays.nbytes>512*2**20:raise RuntimeError('decoded_gray_cache_512MiB')", "needed=set(i for e in edges for i in range(e['a'],e['b']+1));grays={}\n if len(needed)*540*960>512*2**20:raise RuntimeError('decoded_gray_cache_512MiB')")
 change("index=row['index'];rgb=frame.to_ndarray(format='rgb24');grays[index]=cv2.cvtColor(cv2.resize(rgb,(960,540),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY);decoded+=1", "index=row['index'];rgb=frame.to_ndarray(format='rgb24');decoded+=1\n  if index in needed:grays[index]=cv2.cvtColor(cv2.resize(rgb,(960,540),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY)")
 change('assert decoded==901 and len(pixel_verified)==166','assert decoded==901 and len(pixel_verified)==169')
 checkpoint=""" checkpoint={}
 for pid in forward:
  checkpoint[f'f_{pid}']=forward[pid][0];checkpoint[f'fv_{pid}']=forward[pid][1];checkpoint[f'b_{pid}']=backward[pid][0];checkpoint[f'bv_{pid}']=backward[pid][1]
 np.savez_compressed(OUT/'forward-back-checkpoint.npz',**checkpoint)
 if (OUT/'forward-back-checkpoint.npz').stat().st_size>32*2**20:raise RuntimeError('checkpoint32MiB')
"""
 change(' filtered={};reports=[];narrow_report=',checkpoint+' filtered={};reports=[];narrow_report=')
 marker=" if len(selftests)!=8 or not all(r['exact_narrow_strict_mask_equal'] for r in selftests):";assert source.count(marker)==1
 source=source[:source.index(marker)]+" write('new-edge-report.json',dict(status='all24_new_LG_pairs_temporally_validated',new_pairs=len(edges),edge_reports=reports,decoded_source_frames=decoded,all169_RGB_PTS_exact=True,working_gray_frames=len(grays),working_gray_bytes=sum(x.nbytes for x in grays.values()),worker_seconds=time.monotonic()-began,OpenCV_threads=cv2.getNumThreads(),old807_edges_recomputed=0,source_note='original_verified field in edge_reports refers to unverified new LG raw matches; all candidate pairs require fresh RANSAC after temporal filtering'))\n print('ALL24_NEW_TEMPORAL_PAIRS_COMPLETE',flush=True)\n"
 ast.parse(source);(OUT/'generated-worker.py').write_text(source,encoding='utf-8');return source
def worker():
 env=vars(algorithm).copy();env.update(OUT=OUT,DB=DB,PREP=PREP,write=write,affinity=affinity4);text=(OUT/'generated-worker.py').read_text('utf-8');exec(compile(text,str(OUT/'generated-worker.py'),'exec'),env);env['worker']()
def merge():
 import numpy as np,collections
 before=old_hashes(DB);target=BRIDGE/'temporal-filtered169.db'
 if target.exists():raise RuntimeError('existing_derived169_no_overwrite')
 with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target) as dest:
  source.backup(dest);names=dict(dest.execute('SELECT image_id,name FROM images'));new_rows=[]
  for pid,n,c,data in source.execute('SELECT pair_id,rows,cols,data FROM matches WHERE pair_id/2147483647>166 OR pair_id%2147483647>166 ORDER BY pair_id'):
   i,j=divmod(pid,2147483647);a,b=sorted((int(names[i][:-4]),int(names[j][:-4])))
   with np.load(OUT/'edge-flow-evidence'/f'{a}-{b}.npz',allow_pickle=False) as z:
    keep=z['strict_keep'];assert keep.shape==(n,) and np.array_equal(z['source_inlier_indices'],np.flatnonzero(keep));assert not np.any(keep&(~z['per_hop_forward_valid']|~z['per_hop_backward_valid']|(z['forward_endpoint_error_px']>3)|(z['backward_endpoint_error_px']>3)|(z['full_cycle_error_px']>1.5)))
    count=int(keep.sum());m=np.frombuffer(data,dtype='<u4').reshape(n,c);kept=m[keep].copy() if count>=15 else np.empty((0,2),np.uint32);dest.execute('UPDATE matches SET rows=?,cols=2,data=? WHERE pair_id=?',(len(kept),kept.astype('<u4').tobytes(),pid));new_rows.append(dict(pair_id=pid,pair=[a,b],LG_raw=n,strict_temporal=count,retained=len(kept)))
  dest.execute('DELETE FROM two_view_geometries');dest.commit();assert len(new_rows)==24 and dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 if old_hashes(target)!=before:raise RuntimeError('old807_or_old166_features_changed')
 with sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True) as db:
  roots={i:i for i in names};pairs=[];counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('images','keypoints','descriptors','matches','two_view_geometries')}
  def find(i):
   while roots[i]!=i:roots[i]=roots[roots[i]];i=roots[i]
   return i
  for pid,n in db.execute('SELECT pair_id,rows FROM matches WHERE rows>=15'):
   i,j=divmod(pid,2147483647);roots[find(i)]=find(j);pairs.append(names[i]+' '+names[j])
  components=collections.defaultdict(list)
  for i in roots:components[find(i)].append(names[i])
 component_names=sorted((sorted(g) for g in components.values()),key=len,reverse=True);pairfile=BRIDGE/'all-pairs-to-reverify.txt';pairfile.write_text('\n'.join(pairs)+'\n',encoding='ascii')
 result=dict(status='complete169_graph_ready_for_native_partial_or_full_mapping',selected=169,computed_new_pairs=24,new_nonempty_pairs=sum(r['retained']>=15 for r in new_rows),new_empty_pairs=sum(r['retained']==0 for r in new_rows),new_matches=sum(r['retained'] for r in new_rows),old651_good_byteexact=True,old156_empty_never_restored=True,old166_feature_rows_byteexact=True,old_hashes=before,database_counts=counts,nonempty_total_pairs=len(pairs),components=[len(g) for g in component_names],component_image_names=component_names,new_pair_details=new_rows,all_new_results_known=True,old807_results_recomputed=0,old_geometries_cleared=True,new_RANSAC_required=True,derived_DB_sha256=algorithm.sha(target),pairlist_sha256=algorithm.sha(pairfile),thresholds_unchanged=True,source_master_transcoded=False,executionQualified=False,published=False,physicalActions=0)
 (BRIDGE/'temporal-handoff.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('HANDOFF169 '+json.dumps({k:result[k] for k in ('new_nonempty_pairs','new_matches','components','nonempty_total_pairs')}),flush=True)
def launch():
 t=time.monotonic();initial=algorithm.memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6.5*2**30:write('waiting.json',dict(status='admission6_5GiB_wait',memory=initial));return
 if (OUT/'intent.json').exists():raise RuntimeError('single24edge_flow_already_started')
 match=json.loads((BRIDGE/'match-receipt.json').read_text('utf-8'));assert match['new_pairs']==24 and match['status']=='matching_complete_not_flow_filtered' and match['old_raw_pairs_unchanged']
 before=snapshot();generate();write('intent.json',dict(action='only24_new_bridge_edges_strict_temporal_filter',source_hashes=before,base_algorithm_sha256=algorithm.sha(Path(algorithm.__file__)),generated_worker_sha256=algorithm.sha(OUT/'generated-worker.py'),CPU_processors=4,OpenCV_threads=4,hard_seconds=120,runtime_reserve_GiB=4.5,old807_recomputed=0,physicalActions=0));env=os.environ.copy();env['SPHERE_TEMPORAL_CHILD']=str(os.getpid());env['PYTHONPATH']=os.pathsep.join([str(algorithm.ROOT),str(algorithm.ROOT/'.local-pilot/motor-worker-venv/Lib/site-packages')]);samples=[];reason=None
 with (OUT/'worker.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(Path(sys._base_executable)),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=algorithm.memory();samples.append(m)
    if time.monotonic()-t>120:raise RuntimeError('new24_flow_hard120s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 same=before==snapshot()
 if not same:reason='source_hashes_changed'
 write('receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=time.monotonic()-t,source_hashes_unchanged=same,min_available_RAM_GiB=min((m['availableRamBytes'] for m in samples),default=initial['availableRamBytes'])/2**30,min_commit_headroom_GiB=min((m['commitLimitBytes']-m['committedBytes'] for m in samples),default=initial['commitLimitBytes']-initial['committedBytes'])/2**30,CPU_processors=4,OpenCV_threads=4,GPU_initialized=False,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 merge()
if __name__=='__main__':
 if sys.argv[1:]==['--run']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use --run for the single authorized new24 temporal stage.')
