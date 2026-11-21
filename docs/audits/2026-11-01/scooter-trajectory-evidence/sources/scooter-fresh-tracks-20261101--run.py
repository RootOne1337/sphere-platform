"""Official RA+track-only staging, NOT a triangulated scene or route.

--fixture: options/source checks only, no mapping or optimization.
--track-only: coordinator-controlled CPU child, 4 processors / 120 s /
4.5 GiB host RAM and commit reserve. Uses an owned database copy.
No GP, BA, retriangulation, custom union implementation, model downloads or GPU.
"""
import os,sys,json,time,hashlib,sqlite3,subprocess,ctypes,importlib.util,collections
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='1'
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
from scripts.pilot.resource_guard import windows_memory
PREP=ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/prepared'
SOURCE_DB=PREP.parent/'database.db';SOURCE_MODEL=PREP.parent/'models/0'
ADAPTER=ROOT/'.local-pilot/scooter-orientation-prior-20261101/adapter.py'
CANDIDATE=ROOT/'.local-pilot/scooter-calfvo-full-20261101/candidate.npz'
RUNTIME=ROOT/'.local-pilot/reconstruction-tools/pycolmap-4.2.1'
RESERVE=4.5*2**30
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def memory():
 m=windows_memory()
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<RESERVE:raise RuntimeError('host_reserve_4_5GiB')
 return m
def affinity4():
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=4 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:4])))
def sdk():
 sys.path.insert(0,str(RUNTIME));import pycolmap as p
 if p.__version__!='4.2.1':raise RuntimeError('pinned_pycolmap_version')
 return p
def options(p):
 o=p.GlobalPipelineOptions(num_threads=4,random_seed=17,ignore_watermarks=True,multiple_models=False)
 o.mapper.num_threads=4;o.mapper.refine_sensor_from_rig=False
 o.mapper.rotation_averaging.refine_sensor_from_rig=False
 o.mapper.skip_rotation_averaging=False;o.mapper.skip_track_establishment=False
 o.mapper.skip_global_positioning=True;o.mapper.skip_bundle_adjustment=True;o.mapper.skip_retriangulation=True
 # Disabled stages are additionally configured CPU-only, not used as a fallback.
 o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False
 o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=4
 o.mapper.keep_max_num_tracks=30000;o.mapper.track_min_num_views_per_track=3;o.mapper.track_max_num_views_per_track=100;o.mapper.track_intra_image_consistency_threshold=10.
 assert not o.multiple_models and not o.mapper.skip_rotation_averaging and not o.mapper.skip_track_establishment
 assert o.mapper.skip_global_positioning and o.mapper.skip_bundle_adjustment and o.mapper.skip_retriangulation
 return o
def source_snapshot(*,verify_pngs):
 prepared=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'))
 if len(prepared['images'])!=166:raise RuntimeError('expected_166_sources')
 paths=[SOURCE_DB,PREP/'reconstruction-input.json',CANDIDATE,ADAPTER,*SOURCE_MODEL.glob('*.bin')]
 if verify_pngs:
  for row in prepared['images']:
   path=PREP/row['image']
   if sha(path)!=row['png_sha256']:raise RuntimeError('source_PNG_changed')
  paths.extend(PREP/r['image'] for r in prepared['images'])
 return prepared,{str(p.relative_to(ROOT)):sha(p) for p in paths}
def import_adapter():
 spec=importlib.util.spec_from_file_location('_sphere_known_R_adapter',ADAPTER);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def track_stats(rec,p):
 import numpy as np
 per=collections.Counter();distinct=collections.Counter();tracks=collections.Counter()
 for point in rec.points3D.values():
  image_ids={el.image_id for el in point.track.elements};tracks[len(image_ids)]+=1
  if len(image_ids)<3:raise RuntimeError('returned_track_below_three_distinct_views')
  for el in point.track.elements:per[el.image_id]+=1
  for image_id in image_ids:distinct[image_id]+=1
 rows=[dict(image_id=image.image_id,name=image.name,observations=per[image.image_id],distinct_track_count=distinct[image.image_id]) for image in sorted(rec.images.values(),key=lambda x:x.name)]
 values=[r['observations'] for r in rows]
 return dict(track_containers=rec.num_points3D(),registered=rec.num_reg_images(),frames=rec.num_reg_frames(),observations=sum(values),min=min(values),median=float(np.median(values)),p10=float(np.percentile(values,10)),count_under_6=sum(v<6 for v in values),count_under_15=sum(v<15 for v in values),distinct_views_per_track_histogram=dict(tracks),per_frame=rows)
def fixture():
 memory();p=sdk();o=options(p);prepared,hashes=source_snapshot(verify_pngs=False);adapter=import_adapter()
 import numpy as np
 with np.load(CANDIDATE,allow_pickle=False) as data:rotations,binding=adapter.bind_rotations(data['trajectory_c2w'],data['frame_indices'],data['ticks_90k'],prepared)
 if len(rotations)!=166:raise RuntimeError('Calf_binding')
 report=dict(status='options_and_source_binding_fixture_passed',solver_executed=False,track_only_executed=False,source_manifest_sha256=prepared['source_manifest_sha256'],source_hashes=hashes,option_flags=dict(multiple_models=o.multiple_models,skip_rotation_averaging=o.mapper.skip_rotation_averaging,skip_track_establishment=o.mapper.skip_track_establishment,skip_global_positioning=o.mapper.skip_global_positioning,skip_bundle_adjustment=o.mapper.skip_bundle_adjustment,skip_retriangulation=o.mapper.skip_retriangulation,keep_max_num_tracks=o.mapper.keep_max_num_tracks,min_track_views=o.mapper.track_min_num_views_per_track,max_track_views=o.mapper.track_max_num_views_per_track,intra_image_threshold_px=o.mapper.track_intra_image_consistency_threshold),Calf_R_binding=binding,options=str(o),full_raw_graph_claim=False,important_limit='Official rotation averaging still gates registration and PoseGraph valid edges before track establishment; placeholder XYZ is NOT triangulated geometry.',source_modified=False,GPU_initialized=False,physicalActions=0)
 write('fixture.json',report);print(json.dumps({k:report[k] for k in ('status','solver_executed','track_only_executed','option_flags')}))
def worker():
 if os.environ.get('SPHERE_FRESH_TRACK_CHILD')!=str(os.getppid()):raise RuntimeError('owned_parent_required')
 affinity4();memory();p=sdk();o=options(p);adapter=import_adapter()
 import numpy as np
 prepared=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'))
 (OUT/'options.txt').write_text(str(o),encoding='utf-8');write('progress.json',dict(stage='official_RA_and_track_establishment',GP=False,BA=False,retriangulation=False))
 placeholder=OUT/'placeholder-track-containers-NOT-SCENE';placeholder.mkdir(exist_ok=False)
 models=p.global_mapping(OUT/'database-copy.db',PREP/'images',placeholder,options=o)
 if len(models)!=1:raise RuntimeError('expected_one_component')
 rec=next(iter(models.values()));fresh=track_stats(rec,p)
 # Final SIFT contains some 2-view tracks; compare only eligible >=3-view support.
 old=p.Reconstruction(SOURCE_MODEL);eligible=sum(point.track.length()>=3 for point in old.points3D.values())
 write('fresh-support.json',dict(status='fresh_pre_GP_track_containers_only',**fresh,previous_final_SIFT_model_points=old.num_points3D(),previous_final_SIFT_eligible_tracks=eligible,track_budget_applied=30000,budget_saturated=rec.num_points3D()>=30000,triangulated=False,XYZ_must_not_be_interpreted=True,RA_gated_edges=True,executionQualified=False))
 if rec.num_reg_images()!=166:raise RuntimeError('RA_did_not_register_all_166_no_partial_Calf_injection')
 with np.load(CANDIDATE,allow_pickle=False) as data:rotations,binding=adapter.bind_rotations(data['trajectory_c2w'],data['frame_indices'],data['ticks_90k'],prepared)
 oriented,preconditions=adapter.prepare_reconstruction(rec,rotations)
 destination=OUT/'Calf-R-track-containers-NOT-SCENE';destination.mkdir(exist_ok=False);oriented.write(destination)
 write('worker-result.json',dict(status='fresh_tracks_and_Calf_Frame_R_ready_NO_GEOMETRY_SOLVE',fresh_support=fresh,Calf_binding=binding,adapter_preconditions=preconditions,known_R_track_container_path=destination.name,placeholder_model_path='placeholder-track-containers-NOT-SCENE',source_manifest_sha256=prepared['source_manifest_sha256'],global_positioning_executed=False,bundle_adjustment_executed=False,retriangulation_executed=False,Calf_translations_used=False,triangulated=False,independent_pose_truth=False,executionQualified=False,GPU_initialized=False,physicalActions=0))
 print('READY_TRACK_CONTAINERS_NOT_SCENE',flush=True)
def launch():
 start=time.monotonic();initial=memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6.5*2**30:raise RuntimeError('admission_6_5GiB')
 if (OUT/'intent.json').exists() or (OUT/'receipt.json').exists():raise RuntimeError('existing_intent_no_repeat')
 prepared,before=source_snapshot(verify_pngs=True)
 write('intent.json',dict(action='official_RA_plus_fresh_track_establishment_then_Calf_Frame_R_only',source_manifest_sha256=prepared['source_manifest_sha256'],source_hashes=before,CPU_affinity_processors=4,total_seconds=120,host_reserve_GiB=4.5,GP=False,BA=False,retriangulation=False,GPU=False,triangulated_output=False,network=False,physicalActions=0))
 with sqlite3.connect(SOURCE_DB.resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(OUT/'database-copy.db') as target:source.backup(target)
 memory()
 env=os.environ.copy();env['SPHERE_FRESH_TRACK_CHILD']=str(os.getpid())
 # Windows venv redirector creates a grandchild; launch the base interpreter
 # directly so the watchdog owns and can terminate the actual solver process.
 env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(RUNTIME),str(ROOT/'.local-pilot/motor-amd-venv/Lib/site-packages')])
 child_python=Path(sys._base_executable)
 if not child_python.is_file():raise RuntimeError('base_interpreter_missing')
 prior_bootstrap_seconds=1. if (OUT/'bootstrap-refusal-receipt.json').exists() else 0.
 reason=None;child=None;samples=[]
 with (OUT/'worker.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(child_python),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=memory();samples.append(m)
    if time.monotonic()-start+prior_bootstrap_seconds>120:raise RuntimeError('wall_120s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 _,after=source_snapshot(verify_pngs=True)
 if before!=after:reason='source_hashes_changed'
 write('receipt.json',dict(status='track_only_completed' if child.returncode==0 and reason is None else 'stopped_or_failed',exit_code=child.returncode,stop_reason=reason,wall_seconds=time.monotonic()-start,source_hashes_unchanged=before==after,initial_memory=initial,min_available_RAM_GiB=min((m['availableRamBytes'] for m in samples),default=initial['availableRamBytes'])/2**30,min_commit_headroom_GiB=min((m['commitLimitBytes']-m['committedBytes'] for m in samples),default=initial['commitLimitBytes']-initial['committedBytes'])/2**30,only_owned_child_terminated=True,GP_executed=False,BA_executed=False,retriangulation_executed=False,triangulated=False,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 print('OFFICIAL_FRESH_TRACK_STAGE_COMPLETED_NOT_A_3D_SCENE',flush=True)
if __name__=='__main__':
 if sys.argv[1:]==['--fixture']:fixture()
 elif sys.argv[1:]==['--track-only']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use --fixture (read-only) or coordinator-authorized --track-only (owned CPU child).')
