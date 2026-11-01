"""Authorized recovery of missing edges only; immutable sealed results reused.

Derives a reviewable worker from the exact sealed base worker. Only edge
selection, sparse frame caching, CPU profile and checkpoint/finalization change.
No LK, mask, coordinate or acceptance threshold is changed.
"""
import os,sys,time,json,hashlib,sqlite3,subprocess,ctypes,inspect,importlib.util,ast,difflib
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='1'
BASE=Path(__file__).resolve().parent;OUT=BASE/'resume-missing-edges';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('_sealed_temporal_base',BASE/'flow.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
MANIFEST=BASE/'partial-manifest.json'
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def affinity4():
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();a=ctypes.c_size_t();s=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(a),ctypes.byref(s));bits=[1<<i for i in range(64) if a.value&(1<<i)];assert k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
def generate():
 manifest=json.loads(MANIFEST.read_text('utf-8'))
 if base.sha(BASE/'flow.py')!=manifest['algorithm_code_sha256']:raise RuntimeError('base_algorithm_changed')
 for e in manifest['sealed_edges']:
  if base.sha(BASE/e['file'])!=e['NPZ_sha256']:raise RuntimeError('sealed_completed_edge_changed')
 original=inspect.getsource(base.worker);text=original
 def change(a,b):
  nonlocal text
  if text.count(a)!=1:raise RuntimeError('ambiguous_source_adapter:'+a[:60])
  text=text.replace(a,b)
 change('cv2.setNumThreads(2);began=', 'cv2.setNumThreads(4);began=')
 change('assert len(edges)==807 and len(names)==166', "assert len(edges)==807 and len(names)==166\n missing={e['pair_id'] for e in json.loads(MANIFEST.read_text('utf-8'))['uncompleted_unknown_edges']}\n edges=[e for e in edges if e['pid'] in missing]\n assert len(edges)==len(missing)==20")
 change('grays=np.empty((901,540,960),np.uint8)\n if grays.nbytes>512*2**20:raise RuntimeError(\'decoded_gray_cache_512MiB\')', "needed=set(i for e in edges for i in range(e['a'],e['b']+1));grays={}\n if len(needed)*540*960>512*2**20:raise RuntimeError('decoded_gray_cache_512MiB')")
 change("index=row['index'];rgb=frame.to_ndarray(format='rgb24');grays[index]=cv2.cvtColor(cv2.resize(rgb,(960,540),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY);decoded+=1", "index=row['index'];rgb=frame.to_ndarray(format='rgb24');decoded+=1\n  if index in needed:grays[index]=cv2.cvtColor(cv2.resize(rgb,(960,540),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY)")
 checkpoint=""" checkpoint={}
 for pid in forward:
  checkpoint[f'f_{pid}']=forward[pid][0];checkpoint[f'fv_{pid}']=forward[pid][1];checkpoint[f'b_{pid}']=backward[pid][0];checkpoint[f'bv_{pid}']=backward[pid][1]
 np.savez_compressed(OUT/'forward-back-checkpoint.npz',**checkpoint)
 if (OUT/'forward-back-checkpoint.npz').stat().st_size>32*2**20:raise RuntimeError('forward_backward_checkpoint_32MiB')
 write('checkpoint-manifest.json',dict(missing_pair_ids=sorted(forward),base_algorithm_sha256=base.sha(BASE/'flow.py'),partial_manifest_sha256=base.sha(MANIFEST),checkpoint_sha256=base.sha(OUT/'forward-back-checkpoint.npz'),checkpoint_bytes=(OUT/'forward-back-checkpoint.npz').stat().st_size,CPU_processors=4,OpenCV_threads=cv2.getNumThreads(),thresholds_unchanged=True))
"""
 change(' filtered={};reports=[];narrow_report=',checkpoint+' filtered={};reports=[];narrow_report=')
 # Completed edges are never recalculated. The sealed original narrow masks
 # remain the exact-protocol fixtures; they are checked by the final merger.
 tail=" if len(selftests)!=8 or not all(r['exact_narrow_strict_mask_equal'] for r in selftests):"
 if text.count(tail)!=1:raise RuntimeError('tail_boundary')
 text=text[:text.index(tail)]+" write('resume-worker-result.json',dict(status='missing_edges_completed',missing_edges=len(edges),edge_reports=reports,decoded_frames=decoded,cached_gray_frames=len(grays),cached_gray_bytes=sum(x.nbytes for x in grays.values()),worker_seconds=time.monotonic()-began,base_algorithm_sha256=base.sha(BASE/'flow.py'),OpenCV_threads=cv2.getNumThreads(),thresholds_unchanged=True,completed_edges_recomputed=0))\n print('MISSING_EDGE_CYCLES_COMPLETE',flush=True)\n"
 ast.parse(text);(OUT/'generated-worker.py').write_text(text,encoding='utf-8');(OUT/'source-adapter.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='sealed-base-worker',tofile='missing-only-worker')),encoding='utf-8')
 return manifest,text
def worker():
 manifest=json.loads(MANIFEST.read_text('utf-8'));text=(OUT/'generated-worker.py').read_text('utf-8')
 if base.sha(BASE/'flow.py')!=manifest['algorithm_code_sha256']:raise RuntimeError('base_source_changed')
 env=vars(base).copy();env.update(OUT=OUT,BASE=BASE,MANIFEST=MANIFEST,base=base,affinity=affinity4,write=write);exec(compile(text,str(OUT/'generated-worker.py'),'exec'),env);env['worker']()
def merge():
 import numpy as np,collections
 manifest=json.loads(MANIFEST.read_text('utf-8'));source=sqlite3.connect(base.DB.resolve().as_uri()+'?mode=ro',uri=True);names=dict(source.execute('SELECT image_id,name FROM images'));feature_hashes=base.logical_features(source);filtered={};records=[];tests=[];narrow_pairs={tuple(r['pair']) for r in json.loads((base.NARROW/'report.json').read_text('utf-8'))['pairs']};old={e['pair_id']:e for e in manifest['sealed_edges']}
 for index,(pid,n,col,data) in enumerate(source.execute('SELECT pair_id,rows,cols,data FROM two_view_geometries WHERE rows>0 ORDER BY pair_id')):
  ia,ib=divmod(pid,2147483647);a,b=sorted((int(names[ia][:-4]),int(names[ib][:-4])));path=(BASE/old[pid]['file']) if pid in old else OUT/'edge-flow-evidence'/f'{a}-{b}.npz'
  if pid in old and base.sha(path)!=old[pid]['NPZ_sha256']:raise RuntimeError('completed_edge_changed')
  with np.load(path,allow_pickle=False) as z:
   keep=z['strict_keep'];assert keep.shape==(n,) and np.array_equal(z['source_inlier_indices'],np.flatnonzero(keep));assert not np.any(keep&(~z['per_hop_forward_valid']|~z['per_hop_backward_valid']|(z['forward_endpoint_error_px']>3)|(z['backward_endpoint_error_px']>3)|(z['full_cycle_error_px']>1.5)))
   if (a,b) in narrow_pairs:
    with np.load(base.NARROW/f'pair-{a}-{b}.npz',allow_pickle=False) as narrow:equal=np.array_equal(keep,narrow['additional_full_cycle_consistent'])
    tests.append(dict(pair=[a,b],exact_narrow_strict_mask_equal=equal))
   count=int(keep.sum());matches=np.frombuffer(data,dtype='<u4').reshape(n,col)
   # Evidence rows keep source verified row order even when chronological
   # endpoint order required swapping its two feature-index columns.
   retained=matches[keep].copy() if count>=15 else np.empty((0,2),np.uint32);filtered[pid]=retained;records.append(dict(index=index,pair_id=pid,pair=[a,b],original_verified=n,strict_consistent=count,new_raw_rows=len(retained),evidence_sha256=base.sha(path),reused_completed=pid in old))
 assert len(filtered)==807 and len(tests)==8 and all(x['exact_narrow_strict_mask_equal'] for x in tests)
 roots={i:i for i in names}
 def find(i):
  while roots[i]!=i:roots[i]=roots[roots[i]];i=roots[i]
  return i
 for pid,m in filtered.items():
  if len(m):i,j=divmod(pid,2147483647);roots[find(i)]=find(j)
 sizes=sorted(collections.Counter(find(i) for i in names).values(),reverse=True)
 target_path=BASE/'filtered-verified-as-new-raw.db'
 if target_path.exists():raise RuntimeError('existing_derived_DB_no_overwrite')
 with sqlite3.connect(target_path) as target:
  source.backup(target);target.execute('DELETE FROM matches');target.execute('DELETE FROM two_view_geometries')
  for pid,m in filtered.items():target.execute('INSERT INTO matches(pair_id,rows,cols,data) VALUES(?,?,?,?)',(pid,len(m),2,m.astype('<u4').tobytes()))
  target.commit();assert base.logical_features(target)==feature_hashes and target.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and target.execute('SELECT count(*) FROM two_view_geometries').fetchone()[0]==0
 lines=[]
 for pid,m in filtered.items():
  if len(m):i,j=divmod(pid,2147483647);lines.append(names[i]+' '+names[j])
 (BASE/'pairs-to-reverify.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
 first=json.loads((BASE/'flow-receipt.json').read_text('utf-8'));second=json.loads((OUT/'receipt.json').read_text('utf-8'));result=dict(status='full_flow_graph_ready_for_reverification' if sizes==[166] else 'temporal_graph_disconnected_do_not_start_mapping',all_original_edges_completed=807,reused_sealed_completed_edges=len(old),missing_edges_newly_completed=807-len(old),retained_nonempty_edges=len(lines),empty_edges=807-len(lines),retained_matches=sum(len(m) for m in filtered.values()),original_verified_matches=sum(r['original_verified'] for r in records),components=sizes,all_166_connected=sizes==[166],new_raw_definition='Filtered subset of original verified LG inliers, NOT preserved original raw matches',original_SIFT_features_preserved_exact=True,feature_table_sha256=feature_hashes,old_geometries_cleared=True,geometries_reverified=False,narrow_exact_mask_tests=tests,thresholds=json.loads(MANIFEST.read_text('utf-8'))['algorithm_thresholds'],edge_reports=records,base_algorithm_sha256=base.sha(BASE/'flow.py'),derived_DB_sha256=base.sha(target_path),pairs_sha256=base.sha(BASE/'pairs-to-reverify.txt'),source_hashes_unchanged=first['source_hashes_unchanged'] and second['source_hashes_unchanged'],first_worker_receipt=first,resume_worker_receipt=second,cumulative_wall_seconds=first['wall_seconds']+second['wall_seconds'],cumulative_wall_explicitly_exceeds_single_240s_budget=True,completed_flow_results_recomputed=0,GPU_initialized=False,solver_executed=False,physicalActions=0)
 (BASE/'flow-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('MERGED '+json.dumps({k:result[k] for k in ('status','retained_nonempty_edges','retained_matches','components','cumulative_wall_seconds')}),flush=True)
def launch():
 t=time.monotonic();initial=base.memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6*2**30:write('waiting.json',dict(status='waiting_admission6GiB',memory=initial));return
 if (OUT/'intent.json').exists():raise RuntimeError('single_authorized_resume_already_started')
 manifest,text=generate();before=base.snapshot();write('intent.json',dict(action='recover_only_20_missing_edges',source_hashes=before,sealed_partial_manifest_sha256=base.sha(MANIFEST),base_code_sha256=base.sha(BASE/'flow.py'),generated_worker_sha256=base.sha(OUT/'generated-worker.py'),missing_edges=manifest['uncompleted_unknown_edges'],completed_edges_not_recomputed=len(manifest['sealed_edges']),OpenCV_threads=4,CPU_processors=4,hard_seconds=240,admission_GiB=6,runtime_GiB=4.5,physicalActions=0))
 env=os.environ.copy();env['SPHERE_TEMPORAL_CHILD']=str(os.getpid());env['PYTHONPATH']=os.pathsep.join([str(base.ROOT),str(base.ROOT/'.local-pilot/motor-worker-venv/Lib/site-packages')]);samples=[];reason=None
 with (OUT/'worker.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(Path(sys._base_executable)),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=base.memory();samples.append(m)
    if time.monotonic()-t>240:raise RuntimeError('resume_hard240s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 after=base.snapshot();same=before==after
 if not same:reason='source_hashes_changed'
 write('receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=time.monotonic()-t,source_hashes_unchanged=same,min_available_RAM_GiB=min((m['availableRamBytes'] for m in samples),default=initial['availableRamBytes'])/2**30,min_commit_headroom_GiB=min((m['commitLimitBytes']-m['committedBytes'] for m in samples),default=initial['commitLimitBytes']-initial['committedBytes'])/2**30,CPU_processors=4,OpenCV_threads=4,only_missing_edges=True,completed_edges_recomputed=0,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 merge()
if __name__=='__main__':
 if sys.argv[1:]==['--run']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use --run for the single authorized missing-edge recovery.')
