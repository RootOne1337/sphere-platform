"""Continue the SAME authorized recovery from its already-written F/B cache.

Metadata name-shadowing failed before any missing-edge cycle. This continuation
does not rerun forward/back trajectories or any completed edge; its deadline is
the remainder of the original recovery's 240 seconds.
"""
import os,sys,json,time,subprocess,importlib.util,ast
from pathlib import Path
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_authorized_recovery',BASE/'resume.py');resume=importlib.util.module_from_spec(spec);spec.loader.exec_module(resume);base=resume.base;OUT=resume.OUT
def write(name,obj):resume.write(name,obj)
def prepare():
 import numpy as np
 checkpoint=OUT/'forward-back-checkpoint.npz';manifest=json.loads(resume.MANIFEST.read_text('utf-8'))
 if base.sha(BASE/'flow.py')!=manifest['algorithm_code_sha256']:raise RuntimeError('base_code_changed')
 missing={e['pair_id']:e for e in manifest['uncompleted_unknown_edges']}
 with np.load(checkpoint,allow_pickle=False) as z:
  assert len(z.files)==4*len(missing)
  for pid,e in missing.items():
   n=e['verified_inliers']
   assert z[f'f_{pid}'].shape==z[f'b_{pid}'].shape==(n,2) and z[f'fv_{pid}'].shape==z[f'bv_{pid}'].shape==(n,)
   assert np.isfinite(z[f'f_{pid}']).all() and np.isfinite(z[f'b_{pid}']).all()
 source=(OUT/'generated-worker.py').read_text('utf-8')
 # Only the metadata module alias changes; the original function's local
 # Boolean `base` acceptance mask keeps exactly the same meaning.
 source=source.replace('base.sha(', 'sealed_base.sha(')
 begin=source.index(' forward={};backward={}')
 end=source.index(' filtered={};reports=[];',begin)
 load=""" forward={};backward={}
 with np.load(OUT/'forward-back-checkpoint.npz',allow_pickle=False) as checkpoint:
  for e in edges:
   pid=e['pid'];forward[pid]=(checkpoint[f'f_{pid}'].copy(),checkpoint[f'fv_{pid}'].copy());backward[pid]=(checkpoint[f'b_{pid}'].copy(),checkpoint[f'bv_{pid}'].copy())
 write('checkpoint-manifest.json',dict(missing_pair_ids=sorted(forward),base_algorithm_sha256=sealed_base.sha(BASE/'flow.py'),partial_manifest_sha256=sealed_base.sha(MANIFEST),checkpoint_sha256=sealed_base.sha(OUT/'forward-back-checkpoint.npz'),checkpoint_bytes=(OUT/'forward-back-checkpoint.npz').stat().st_size,CPU_processors=4,OpenCV_threads=cv2.getNumThreads(),thresholds_unchanged=True,forward_backward_recomputed=False))
"""
 source=source[:begin]+load+source[end:];ast.parse(source);(OUT/'continue-worker.py').write_text(source,encoding='utf-8')
 return source,base.sha(checkpoint)
def worker():
 text=(OUT/'continue-worker.py').read_text('utf-8');env=vars(base).copy();env.update(OUT=OUT,BASE=BASE,MANIFEST=resume.MANIFEST,base=base,sealed_base=base,affinity=resume.affinity4,write=write);exec(compile(text,str(OUT/'continue-worker.py'),'exec'),env);env['worker']()
def launch():
 t=time.monotonic();initial=base.memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6*2**30:raise RuntimeError('admission6GiB')
 if (OUT/'continuation-intent.json').exists():raise RuntimeError('continuation_already_started')
 prior=json.loads((OUT/'receipt.json').read_text('utf-8'));assert prior['status']=='stopped_or_failed' and prior['source_hashes_unchanged']
 spent=prior['wall_seconds'];remaining=240-spent;assert remaining>0
 text,checkpoint_sha=prepare();before=base.snapshot()
 for e in json.loads(resume.MANIFEST.read_text('utf-8'))['sealed_edges']:
  if base.sha(BASE/e['file'])!=e['NPZ_sha256']:raise RuntimeError('completed_edge_changed')
 write('setup-failure-receipt.json',prior);write('continuation-intent.json',dict(action='finish_missing_cycles_from_persisted_F_B',already_spent_recovery_seconds=spent,remaining_same_recovery_seconds=remaining,checkpoint_sha256=checkpoint_sha,continuation_code_sha256=base.sha(OUT/'continue-worker.py'),source_hashes=before,forward_backward_recomputed=False,completed_edges_recomputed=0,CPU_processors=4,OpenCV_threads=4,thresholds_unchanged=True,physicalActions=0))
 env=os.environ.copy();env['SPHERE_TEMPORAL_CHILD']=str(os.getpid());env['PYTHONPATH']=os.pathsep.join([str(base.ROOT),str(base.ROOT/'.local-pilot/motor-worker-venv/Lib/site-packages')]);samples=[];reason=None
 with (OUT/'continuation.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(Path(sys._base_executable)),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=base.memory();samples.append(m)
    if time.monotonic()-t>remaining:raise RuntimeError('same_recovery_total240s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 same=before==base.snapshot() and checkpoint_sha==base.sha(OUT/'forward-back-checkpoint.npz')
 if not same:reason='source_or_checkpoint_changed'
 elapsed=time.monotonic()-t
 write('continuation-receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=elapsed,source_hashes_unchanged=same,forward_backward_recomputed=False,completed_edges_recomputed=0,physicalActions=0))
 write('receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=spent+elapsed,source_hashes_unchanged=same,first_recovery_setup_seconds=spent,cached_cycle_continuation_seconds=elapsed,same_recovery_deadline_seconds=240,min_available_RAM_GiB=min([prior['min_available_RAM_GiB']]+[m['availableRamBytes']/2**30 for m in samples]),min_commit_headroom_GiB=min([prior['min_commit_headroom_GiB']]+[(m['commitLimitBytes']-m['committedBytes'])/2**30 for m in samples]),CPU_processors=4,OpenCV_threads=4,only_missing_edges=True,completed_edges_recomputed=0,forward_backward_recomputed_in_continuation=False,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 resume.merge()
if __name__=='__main__':
 if sys.argv[1:]==['--run']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use --run only for the existing authorized recovery remainder.')
