"""One coordinated CPU global-positioning solve on fresh official tracks.

Fixed source-bound CalfVO rotations, new random centers/points, no Calf
translations, no rotation averaging, BA or retriangulation in this phase.
Reports identical 2D observation keys against the original final SIFT model.
"""
import os,sys,time,json,hashlib,sqlite3,subprocess,importlib.util,collections
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='1'
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1];OUT=BASE/'known-R-global-positioning'
spec=importlib.util.spec_from_file_location('_fresh_track_stage',BASE/'run.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
TRACK_MODEL=BASE/'Calf-R-track-containers-NOT-SCENE'
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def protected():
 _,result=stage.source_snapshot(verify_pngs=True)
 for path in [BASE/'database-copy.db',BASE/'fresh-support.json',BASE/'worker-result.json',*TRACK_MODEL.glob('*.bin')]:result[str(path.relative_to(ROOT))]=stage.sha(path)
 return result
def error_summary(values):
 import numpy as np
 values=np.asarray(values,dtype=float)
 return dict(n=len(values),mean=float(values.mean()) if len(values) else None,median=float(np.median(values)) if len(values) else None,p95=float(np.percentile(values,95)) if len(values) else None,max=float(values.max()) if len(values) else None)
def observation_errors(rec):
 import numpy as np
 found={};per=collections.defaultdict(list)
 for pid,point in rec.points3D.items():
  if len({el.image_id for el in point.track.elements})<3:continue
  for el in point.track.elements:per[el.image_id].append((el.point2D_idx,point.xyz.copy()))
 for image_id,items in per.items():
  image=rec.image(image_id);xyz=np.asarray([row[1] for row in items]);ids=[row[0] for row in items];pose=image.cam_from_world();cam=xyz@pose.rotation.matrix().T+pose.translation
  assert image.camera.model_name=='SIMPLE_PINHOLE';f,cx,cy=image.camera.params
  for index,pc in zip(ids,cam):
   xy=image.point2D(index).xy;key=(image_id,int(index))
   if not np.isfinite(pc).all() or abs(pc[2])<1e-12:found[key]=(None,False);continue
   uv=np.array([f*pc[0]/pc[2]+cx,f*pc[1]/pc[2]+cy]);err=float(np.linalg.norm(uv-xy));found[key]=(err,bool(pc[2]>0))
 return found
def worker():
 if os.environ.get('SPHERE_FRESH_GP_CHILD')!=str(os.getppid()):raise RuntimeError('owned_parent_required')
 stage.affinity4();stage.memory();p=stage.sdk();adapter=stage.import_adapter()
 import numpy as np
 rec=p.Reconstruction(TRACK_MODEL);before_R={i:im.cam_from_world().rotation.matrix().copy() for i,im in rec.images.items()};before_K={i:c.params.copy() for i,c in rec.cameras.items()}
 graph,cache=adapter.load_pose_graph_for_execution(OUT/'database-copy.db');opts=adapter.global_positioning_options()
 write('progress.json',dict(stage='run_global_positioning',called=True,fixed_Calf_R=True,BA=False,retriangulation=False))
 t=time.monotonic();success=p.run_global_positioning(opts,graph,rec);solve_seconds=time.monotonic()-t
 if not success:raise RuntimeError('global_positioning_solution_not_usable')
 maxR=max(float(np.max(np.abs(im.cam_from_world().rotation.matrix()-before_R[i]))) for i,im in rec.images.items())
 if maxR>1e-10 or not all(np.array_equal(before_K[i],c.params) for i,c in rec.cameras.items()):raise RuntimeError('fixed_R_or_intrinsics_changed')
 gauge=adapter.center_first_camera_gauge(rec,'00000000.png');rec.update_point_3d_errors()
 destination=OUT/'experimental-GP-model-NOT-NAVIGATION';destination.mkdir(exist_ok=False);rec.write(destination)
 old=p.Reconstruction(stage.SOURCE_MODEL);source_errors=observation_errors(old);new_errors=observation_errors(rec);common=sorted(set(source_errors)&set(new_errors));per_frame=[];old_finite=[];new_finite=[];old_positive=[];new_positive=[]
 for image_id,image in sorted(rec.images.items()):
  keys=[k for k in common if k[0]==image_id];both=[k for k in keys if source_errors[k][0] is not None and new_errors[k][0] is not None];positive=[k for k in both if source_errors[k][1] and new_errors[k][1]]
  a=[source_errors[k][0] for k in both];b=[new_errors[k][0] for k in both];aa=[source_errors[k][0] for k in positive];bb=[new_errors[k][0] for k in positive];old_finite.extend(a);new_finite.extend(b);old_positive.extend(aa);new_positive.extend(bb)
  per_frame.append(dict(image_id=image_id,name=image.name,shared_2D_observation_keys=len(keys),same_finite_source=error_summary(a),same_finite_fresh_known_R_GP=error_summary(b),same_positive_source=error_summary(aa),same_positive_fresh_known_R_GP=error_summary(bb)))
 # Assessment is evaluated on an in-memory copy so no report helper can change
 # the serialized experimental model or source models.
 from scripts.pilot.reconstruct_route import model_assessment
 _,assessment=model_assessment(p.Reconstruction(rec),stage.PREP,166,0.,35.493)
 report=dict(status='fresh_track_known_R_GP_completed_UNQUALIFIED',solver_success=True,solve_seconds=solve_seconds,options=str(opts),registered=rec.num_reg_images(),fresh_point_track_containers=rec.num_points3D(),same_2D_observations=dict(common_keys=len(common),policy='Same (image_id,point2D_idx) keys, original final SIFT versus fresh GP. Finite signed projections and common-positive-depth projections reported separately; not independent holdout.',finite_source=error_summary(old_finite),finite_fresh_known_R_GP=error_summary(new_finite),positive_depth_both_source=error_summary(old_positive),positive_depth_both_fresh_known_R_GP=error_summary(new_positive)),all_new_observations=dict(total=len(new_errors),behind_or_nonprojectable=sum(not positive for error,positive in new_errors.values()),nonprojectable=sum(error is None for error,positive in new_errors.values()),finite_reprojection=error_summary([error for error,positive in new_errors.values() if error is not None])),per_frame=per_frame,max_fixed_rotation_matrix_change=maxR,intrinsics_unchanged=True,first_camera_center_gauge_translation_removed=gauge,assessment=assessment,BA_executed=False,retriangulation_executed=False,Calf_translations_used=False,fresh_tracks_RA_gated=True,independent_pose_holdout=False,calibration_truth=False,navigation_qualified=False,executionQualified=False,source_modified=False,physicalActions=0)
 write('assessment.json',report);write('progress.json',dict(stage='complete_UNQUALIFIED',solver_success=True,GP_seconds=solve_seconds));print(json.dumps({k:report[k] for k in ('status','solve_seconds','registered','same_2D_observations','all_new_observations')}),flush=True)
def launch():
 t=time.monotonic();initial=stage.memory()
 if min(initial['availableRamBytes'],initial['commitLimitBytes']-initial['committedBytes'])<6.5*2**30:raise RuntimeError('GP_admission_6_5GiB')
 if OUT.exists():raise RuntimeError('existing_GP_directory_no_repeat')
 if json.loads((BASE/'receipt.json').read_text('utf-8'))['status']!='track_only_completed':raise RuntimeError('track_stage_not_valid')
 OUT.mkdir();before=protected();write('intent.json',dict(action='one_direct_CPU_global_positioning_with_fresh_official_tracks_and_fixed_Calf_R',source_hashes=before,CPU_processors=4,wall_seconds=180,admission_GiB=6.5,runtime_reserve_GiB=4.5,BA=False,retriangulation=False,Calf_translations=False,independent_pose_truth=False,physicalActions=0))
 with sqlite3.connect((BASE/'database-copy.db').resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(OUT/'database-copy.db') as dst:src.backup(dst)
 env=os.environ.copy();env['SPHERE_FRESH_GP_CHILD']=str(os.getpid());env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(stage.RUNTIME),str(ROOT/'.local-pilot/motor-amd-venv/Lib/site-packages')]);samples=[];reason=None
 with (OUT/'worker.log').open('x',encoding='utf-8') as log:
  child=subprocess.Popen([str(Path(sys._base_executable)),'-B',str(Path(__file__).resolve()),'--worker'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  while child.poll() is None:
   try:
    m=stage.memory();samples.append(m)
    if time.monotonic()-t>180:raise RuntimeError('GP_wall_180s')
   except RuntimeError as exc:reason=str(exc);child.kill();child.wait();break
   time.sleep(.2)
 after=protected()
 if before!=after:reason='source_hashes_changed'
 write('receipt.json',dict(status='completed' if child.returncode==0 and reason is None else 'failed_or_stopped',exit_code=child.returncode,stop_reason=reason,wall_seconds=time.monotonic()-t,source_hashes_unchanged=before==after,min_available_RAM_GiB=min((m['availableRamBytes'] for m in samples),default=initial['availableRamBytes'])/2**30,min_commit_headroom_GiB=min((m['commitLimitBytes']-m['committedBytes'] for m in samples),default=initial['commitLimitBytes']-initial['committedBytes'])/2**30,owned_direct_base_interpreter_child=True,CPU_processors=4,GPU=False,BA=False,retriangulation=False,physicalActions=0))
 if child.returncode or reason:raise SystemExit(2)
 print('FRESH_KNOWN_R_GP_ASSESSED_NOT_QUALIFIED',flush=True)
if __name__=='__main__':
 if sys.argv[1:]==['--run']:launch()
 elif sys.argv[1:]==['--worker']:worker()
 else:raise SystemExit('Use coordinator-authorized --run only.')
