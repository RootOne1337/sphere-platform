"""Read-only frontier analysis plus exactly three real new RGB source PNGs."""
import os,sys,time,json,sqlite3,hashlib,shutil,threading,ctypes
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='2'
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
from scripts.pilot.resource_guard import windows_memory
start=time.monotonic();done=threading.Event();minram=2**63
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def guard():
 global minram
 m=windows_memory();minram=min(minram,m['availableRamBytes'])
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*2**30 or time.monotonic()-start>30:raise RuntimeError('frontier_CPU30s_host4_5GiB')
guard()
def watch():
 while not done.wait(.2):
  try:guard()
  except Exception as e:write('refusal.json',dict(reason=str(e)));os._exit(4)
threading.Thread(target=watch,daemon=True).start()
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();a=ctypes.c_size_t();s=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(a),ctypes.byref(s));bits=[1<<i for i in range(64) if a.value&(1<<i)];assert k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:2])))
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from motor_worker.browser_teach import validate_browser,decoded_browser
PREP=ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/prepared';FLOW=ROOT/'.local-pilot/scooter-temporal-flow-full-20261101';CAPTURE=ROOT/'.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input';BRIDGE=ROOT/'.local-pilot/scooter-temporal-bridge-20261101';DEST=BRIDGE/'prepared'
try:
 if (OUT/'plan.json').exists():raise RuntimeError('frontier_plan_already_exists_no_repeat')
 meta=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'));selected=sorted(meta['images'],key=lambda r:r['source_index']);by={r['source_index']:r for r in selected};handoff=json.loads((FLOW/'handoff.json').read_text('utf-8'));flow=json.loads((FLOW/'flow-report.json').read_text('utf-8'));edge_report={tuple(e['pair']):e for e in flow['edge_reports']};components={i:ci for ci,c in enumerate(handoff['components']) for i in c['source_indices']};capture=validate_browser(CAPTURE);assert len(selected)==166 and len(capture.frames)==901 and sha(CAPTURE/'manifest.json')==meta['source_manifest_sha256']
 protected=[PREP/'reconstruction-input.json',PREP.parent/'database.db',FLOW/'filtered-verified-as-new-raw.db',FLOW/'flow-report.json',*[CAPTURE/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]];before={str(p.relative_to(ROOT)):sha(p) for p in protected}
 boundaries=[];new_indices=set()
 for ra,rb in zip(selected,selected[1:]):
  a,b=ra['source_index'],rb['source_index']
  if components[a]==components[b]:continue
  available=list(range(a+1,b));choice=[available[int(i)] for i in np.linspace(0,len(available)-1,min(4,len(available)),dtype=int)] if available else [];new_indices.update(choice);e=edge_report[(a,b)]
  path=FLOW/'edge-flow-evidence'/f'{a}-{b}.npz'
  if not path.exists():path=FLOW/'resume-missing-edges/edge-flow-evidence'/f'{a}-{b}.npz'
  with np.load(path,allow_pickle=False) as z:
   fv,bv=z['per_hop_forward_valid'],z['per_hop_backward_valid'];both=fv&bv;near=both&(z['forward_endpoint_error_px']<=3)&(z['backward_endpoint_error_px']<=3);reason=dict(forward_per_hop_FB_valid=int(fv.sum()),backward_per_hop_FB_valid=int(bv.sum()),both_per_hop_FB_valid=int(both.sum()),both_endpoint_le3=int(near.sum()),full_cycle_and_all_gates=int(z['strict_keep'].sum()),threshold15_cleared_edge=e['new_raw_rows']==0)
  boundaries.append(dict(start_source_index=a,end_source_index=b,start_PTS=ra['relative_ticks_90k'],end_PTS=rb['relative_ticks_90k'],start_seconds=ra['relative_ticks_90k']/90000,end_seconds=rb['relative_ticks_90k']/90000,components=[components[a],components[b]],real_missing_indices=available,new_source_indices=choice,original_verified_inliers=e['original_verified'],remaining_edge_matches=e['new_raw_rows'],reason=reason,interpretation='No intermediate source frame exists in this interval.' if not available else 'Newly selected frames already existed in the continuous LK decode; novelty is new feature anchors, not invented motion observations.'))
 assert new_indices=={501,502,503} and len(new_indices)<=12 and len(selected)+len(new_indices)<=240
 DEST.mkdir(exist_ok=False);(DEST/'images').mkdir();new={};decoded=0
 for row,frame in decoded_browser(capture):
  decoded+=1;i=row['index']
  if i in new_indices:
   rgb=frame.to_ndarray(format='rgb24');path=DEST/'images'/f'{i:08d}.png';Image.fromarray(rgb).save(path);assert np.array_equal(np.asarray(Image.open(path).convert('RGB')),rgb)
   new[i]=dict(image='images/'+path.name,source_index=i,relative_ticks_90k=row['relative_ticks_90k'],worker_observed_at_ms=row['worker_observed_at_ms'],source_access_unit_sha256=row['sha256'],png_sha256=sha(path),rgb_pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),bytes=path.stat().st_size)
 assert decoded==901 and set(new)==new_indices
 for index,row in enumerate(selected):
  source=PREP/row['image'];target=DEST/row['image'];assert sha(source)==row['png_sha256'];shutil.copyfile(source,target);assert sha(target)==row['png_sha256']
  if index%20==0:guard()
 metadata={**meta,'images':sorted(selected+list(new.values()),key=lambda r:r['source_index']),'selection':'temporal_component_frontiers_three_real_source_frames','sampling':{'method':'preserve_original166_add_exact_source501_502_503','poses_interpolated':False,'images_generated':False,'new_feature_anchors_only':True},'prepared_bytes':sum(r['bytes'] for r in selected+list(new.values()))}
 (DEST/'reconstruction-input.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
 anchors=[497,498,499,500,504,509,515];pairs=sorted({tuple(sorted((i,j))) for i in new_indices for j in anchors}|{(501,502),(501,503),(502,503)})
 assert len(pairs)==24 and all(abs(capture.frames[a]['relative_ticks_90k']-capture.frames[b]['relative_ticks_90k'])<=90000 for a,b in pairs)
 for name in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE'):assert sha(CAPTURE/name)==before[str((CAPTURE/name).relative_to(ROOT))]
 panels=[];font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
 for i in (497,498,499,500,501,502,503,504,509):
  rgb=Image.open(DEST/'images'/f'{i:08d}.png').convert('RGB').resize((640,360),Image.Resampling.LANCZOS);panel=Image.new('RGB',(640,398),(12,18,26));panel.paste(rgb,(0,38));draw=ImageDraw.Draw(panel);draw.text((8,8),f'SOURCE {i} | PTS {capture.frames[i]["relative_ticks_90k"]} | {capture.frames[i]["relative_ticks_90k"]/90000:.3f}s | '+('NEW REAL FRAME' if i in new_indices else f'OLD component {components[i]}'),font=font,fill='white');panels.append(panel)
 sheet=Image.new('RGB',(1920,1194),(12,18,26))
 for index,panel in enumerate(panels):sheet.paste(panel,((index%3)*640,(index//3)*398))
 sheet.save(OUT/'frontier-contact.png')
 after={str(p.relative_to(ROOT)):sha(p) for p in protected};assert before==after
 report=dict(status='source_bound_frontier_plan_and_169_workspace_ready',boundaries=boundaries,new_frames=list(new.values()),new_views=3,total_selected_views=169,view_cap=240,old651good_edges_preserve=True,old156empty_edges_never_restore=True,new_pair_plan=pairs,new_pairs=24,anchors_from_components={'last3component94':[497,498,499],'isolated':[500],'first3component71':[504,509,515]},new_pair_max_time_seconds=max(abs(capture.frames[a]['relative_ticks_90k']-capture.frames[b]['relative_ticks_90k'])/90000 for a,b in pairs),prepared_path=str(DEST.relative_to(ROOT)),source_manifest_sha256=meta['source_manifest_sha256'],source_hashes=before,source_hashes_unchanged=True,source_master_transcoded=False,real_source_decode_count=decoded,new_PNG_count=3,no_hardlinks_created=True,contact='frontier-contact.png',why_not_a_guarantee='The full LK audit already traversed frames501..503. Selecting them for SIFT adds feature identities/track anchors, not unobserved motion. Frame499->500 has no extra source frame; preserving the same strict flow gates may still prevent a bridge. No bad old edge will be restored.',wall_seconds=time.monotonic()-start,min_available_RAM_GiB=minram/2**30,GPU_initialized=False,solver_executed=False,physicalActions=0)
 write('plan.json',report);(BRIDGE/'bridge-plan.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ('status','new_views','total_selected_views','new_pairs','new_pair_max_time_seconds','wall_seconds','min_available_RAM_GiB')}))
finally:done.set()
