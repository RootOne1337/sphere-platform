"""Evaluate frozen fusion scores with the actual CausalSequenceBeam, no authority."""
import os,sys,json,time,pathlib,hashlib,subprocess
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-image-route-20261101/minimap-fusion');base=root.parent;inputs=[root/'fusion-scores.npz',root/'summary.json',root/'dp-results.json',base/'query-metrics.json',pathlib.Path('motor_worker/image_route_sequence.py')]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 intent={'method':'motor_worker.image_route_sequence.CausalSequenceBeam with default options','dataset':'frozen same-video 100x169 world+minimap scores; optional HUD evidence valid only for this clip','receipt_clock':'zero-latency, monotonically increasing virtual elapsed time from query PTS, reversed order reflected','source_sequence':'monotonically increasing delivery counter; source image index separate','checked':'frozen checked matrix; excluded must be unchecked','authority':False,'navigation_qualified':False,'execution_qualified':False,'no_new_extraction':True};(root/'production-beam-intent.json').write_text(json.dumps(intent,indent=2));before={str(p):sha(p) for p in inputs};m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];start=time.monotonic();samples=[];reason=None;code=None
 if min(v)>=4.5*2**30:
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/motor-worker-venv/Lib/site-packages').resolve())])
  with (root/'production-beam-worker.log').open('w') as log:
   child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),'worker'],env=env,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*2**30 or time.monotonic()-start>10:reason='memory_guard' if min(v)<4.5*2**30 else 'timeout';child.kill();child.wait();break
    time.sleep(.1)
   code=child.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in inputs};receipt={'input_hashes_before':before,'input_hashes_unchanged':before==after,'exit':code,'stop':reason,'seconds':time.monotonic()-start,'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'owned_direct_child_only':True,'no_actions':True};(root/'production-beam-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True);sys.exit()
from dataclasses import asdict
import numpy as np
from motor_worker.image_route_sequence import CausalSequenceBeam
z=np.load(root/'fusion-scores.npz');scores=z['scores'];checked=z['checked'];excluded=z['excluded'];idx=z['query_indices'];ticks=z['query_ticks_90k'];refidx=z['reference_indices'];rt=z['reference_ticks_90k'];raw=json.loads((base/'query-metrics.json').read_text())['queries'];metadata={r['query_index']:r for r in raw};original=json.loads((root/'dp-results.json').read_text());assert scores.shape==(100,169) and not np.any(checked&excluded) and np.all(np.diff(ticks)>0);refs=tuple(float(t)/90000 for t in rt)
def evaluate(order,kind):
 beam=CausalSequenceBeam(refs);rows=[];previous={r['query_index']:r for r in original[kind]['rows']};mismatch=[];first=int(ticks[order[0]])
 for count,i in enumerate(order,1):
  t=1.+abs(int(ticks[i])-first)/90000.;ev=beam.update(scores[i].astype(float).tolist(),source_sequence=count,received_at=t,source_sha256=metadata[int(idx[i])]['bgr_sha256'],now=t,checked=checked[i].tolist());raw_evidence=asdict(ev);selected=int(refidx[ev.index]) if ev.index is not None else None;delta=abs(int(rt[ev.index])-int(ticks[i]))/90000. if ev.index is not None else None;expected=previous[int(idx[i])]['chosen_reference_index']
  if selected!=expected:mismatch.append({'query_index':int(idx[i]),'typed_selected':selected,'research_selected':expected,'typed_status':ev.status,'research_candidate':previous[int(idx[i])]['candidate_reference_index']})
  rows.append({'query_index':int(idx[i]),'source_ticks_90k':int(ticks[i]),'virtual_receipt_seconds':t,'delivery_sequence':count,'source_sha256':metadata[int(idx[i])]['bgr_sha256'],'selected_reference_source_index':selected,'selected_reference_array_index':ev.index,'same_video_time_error_seconds':delta,'same_video_hit_within_0_6_seconds':bool(delta is not None and delta<=.6),'same_video_wrong_over_2_seconds':bool(delta is not None and delta>2),'evidence':raw_evidence})
 known=sum(x['evidence']['status']=='reference_selected' for x in rows);return {'rows':rows,'summary':{'queries':len(rows),'known':known,'unknown_or_ambiguous_or_stale':len(rows)-known,'status_counts':{s:sum(x['evidence']['status']==s for x in rows) for s in ('reference_selected','unknown','ambiguous','stale')},'same_video_hit_within_0_6s':sum(x['same_video_hit_within_0_6_seconds'] for x in rows),'same_video_wrong_over_2s':sum(x['same_video_wrong_over_2_seconds'] for x in rows),'denominator':'all 100 queries including unknown','research_count_expected':original[kind]['summary']['known'],'row_mismatches':len(mismatch),'mismatches':mismatch}}
forward=evaluate(list(range(100)),'forward');reverse=evaluate(list(range(99,-1,-1)),'reverse');result={'forward':forward,'reverse':reverse,'source_authority':False,'execution_qualified':False,'caveat':'Optional minimap evidence for this specific game/HUD and same-video time proxy; no independent repeat, true pose, physical location or action authority.'};(root/'production-beam-results.json').write_text(json.dumps(result,indent=2));(root/'production-beam-summary.json').write_text(json.dumps({'forward':forward['summary'],'reverse':reverse['summary'],'source_authority':False,'execution_qualified':False,'same_video_only':True,'minimap_optional_clip_specific':True},indent=2));print(json.dumps({'forward':forward['summary'],'reverse':reverse['summary']}),flush=True)
