"""Read-only descriptive parallax for estimated track/camera geometry."""
import os,sys,json,hashlib,time,traceback
from pathlib import Path
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
sys.path.insert(0,os.getcwd());sys.path.insert(0,str(Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import cv2,numpy as np,pycolmap as p
from scripts.pilot.resource_guard import windows_memory
cv2.setNumThreads(2)
out=Path('.local-pilot/scooter-parallax-audit-20261101');new=Path('.local-pilot/scooter-stage-global-20261101/models/0');base=Path('.local-pilot/scooter-intrinsics-20261101/960/models/0');start=time.monotonic();G=1024**3
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def guard():
 m=windows_memory();r=m['availableRamBytes'];c=m['commitLimitBytes']-m['committedBytes']
 if min(r,c)<4.5*G:raise RuntimeError(f'resource_guard:ram={r}:commit={c}')
 if time.monotonic()-start>42:raise TimeoutError('internal_deadline')
def stats(values):
 if not values:return {'count':0}
 a=np.asarray(values,dtype=float);return {'count':len(a),'min':float(a.min()),'p10':float(np.percentile(a,10)),'median':float(np.median(a)),'p90':float(np.percentile(a,90)),'p99':float(np.percentile(a,99)),'max':float(a.max()),'below_1_deg':int((a<1).sum()),'below_2_deg':int((a<2).sum()),'below_3_deg':int((a<3).sum()),'below_5_deg':int((a<5).sum())}
def max_angle(centers,point):
 rays=point-centers;norm=np.linalg.norm(rays,axis=1)
 if np.any(norm<=1e-12):return None
 rays=rays/norm[:,None];cos=np.clip(rays@rays.T,-1,1)
 # COLMAP-style acute triangulation angle: theta and 180-theta are equivalent.
 angles=np.arccos(np.abs(cos))*180/np.pi
 return float(np.max(angles))
def analyze(path):
 rec=p.Reconstruction(path);ims={i:im for i,im in rec.images.items() if im.has_pose};cam={i:(im.cam_from_world().inverse().translation,im.cam_from_world().rotation.matrix(),im.cam_from_world().translation) for i,im in ims.items()}
 vals={'all':[],'top_quarter_majority':[],'other_tracks':[]};positive=total=invalid=0;length=[]
 for j,point in enumerate(rec.points3D.values()):
  if j%250==0:guard()
  xyz=point.xyz;centers=[];ys=[]
  for el in point.track.elements:
   if el.image_id not in cam:continue
   center,Rcw,tcw=cam[el.image_id];centers.append(center);ys.append(float(ims[el.image_id].point2D(el.point2D_idx).xy[1]));total+=1;positive+=int((Rcw@xyz+tcw)[2]>0)
  if len(centers)<2:invalid+=1;continue
  angle=max_angle(np.asarray(centers),xyz)
  if angle is None or not np.isfinite(angle):invalid+=1;continue
  vals['all'].append(angle);top=sum(y<270 for y in ys)>len(ys)/2;vals['top_quarter_majority' if top else 'other_tracks'].append(angle);length.append(len(ys))
 length_stats=stats(length);length_stats={k:v for k,v in length_stats.items() if not k.startswith('below_')}
 return {'registered_images':len(ims),'points_total':rec.num_points3D(),'invalid_or_less_than_two_observations':invalid,'positive_depth_observations':positive,'total_observations':total,'track_length':length_stats,'max_acute_triangulation_angle_deg':{k:stats(v) for k,v in vals.items()}}
try:
 expected=float(np.degrees(np.arctan(.1)));actual=max_angle(np.array([[0.,0.,0.],[1.,0.,0.]]),np.array([0.,0.,10.]))
 if abs(expected-actual)>1e-9:raise RuntimeError('synthetic_angle_fixture_failed')
 files=[m/n for m in (base,new) for n in ('cameras.bin','images.bin','points3D.bin','frames.bin','rigs.bin')];before={str(x):sha(x) for x in files}
 o=p.GlobalPipelineOptions(num_threads=2,random_seed=17,ignore_watermarks=True);o.mapper.num_threads=2;o.mapper.refine_sensor_from_rig=False;o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False;o.mapper.rotation_averaging.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_focal_length=False;o.mapper.bundle_adjustment.refine_extra_params=False;o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=2;o.mapper.bundle_adjustment.ceres.solver_options.max_num_iterations=30;o.mapper.keep_max_num_tracks=30000
 v=p.TwoViewGeometryOptions();v.ransac.num_threads=1;v.filter_stationary_matches=False
 options={'global_mapper_min_tri_angle_deg':o.mapper.min_tri_angle_deg,'retriangulation_min_angle_deg':o.mapper.retriangulation.min_angle,'retriangulation_ignore_two_view_tracks':o.mapper.retriangulation.ignore_two_view_tracks,'retriangulation_re_min_ratio':o.mapper.retriangulation.re_min_ratio,'retriangulation_re_max_trials':o.mapper.retriangulation.re_max_trials,'track_min_num_views':o.mapper.track_min_num_views_per_track,'track_max_num_views':o.mapper.track_max_num_views_per_track,'keep_max_num_tracks':o.mapper.keep_max_num_tracks,'global_positioning_min_views':o.mapper.global_positioning.min_num_view_per_track,'skip_retriangulation':o.mapper.skip_retriangulation,'decompose_relative_pose':o.decompose_relative_pose,'min_num_matches':o.min_num_matches,'refine_focal_length':o.mapper.bundle_adjustment.refine_focal_length,'max_angular_reprojection_deg':o.mapper.max_angular_reproj_error_deg,'max_normalized_reprojection':o.mapper.max_normalized_reproj_error,'new_graph_two_view_options':{'min_num_inliers':v.min_num_inliers,'ransac_max_error_px':v.ransac.max_error,'ransac_confidence':v.ransac.confidence,'filter_stationary_matches':v.filter_stationary_matches,'compute_relative_pose':v.compute_relative_pose,'ransac_num_threads':v.ransac.num_threads},'pycolmap_version':p.__version__}
 results={'baseline_f960':analyze(base),'new_global_f960':analyze(new)};after={str(x):sha(x) for x in files}
 report={'status':'complete','fixture_expected_deg':expected,'fixture_actual_deg':actual,'models':results,'effective_options_reconstructed_from_identical_run_scripts':options,'source_hashes_before':before,'source_hashes_after':after,'source_unchanged':before==after,'elapsed_s':time.monotonic()-start,'method':'For each reconstructed 3D point, compute all pairwise acute angles between normalized vectors from registered estimated camera centers to that point; report maximum. Top-quarter-majority means more than half observed 2D keypoint y coordinates <270 in 1080px images. Positive depth based on each estimated camera world-to-camera transform.','limitations':'Conditional on camera centers and 3D points estimated by the same problematic models; not independently measured parallax, scene depth, sky truth, or causal proof. Thresholds of a mapper may apply at another stage, to another pair, prior to BA or rejection; final angles below defaults do not prove filter failure. Top image is not semantic sky.'}
 (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False));print(json.dumps(report,indent=2),flush=True)
except Exception as e:
 m=windows_memory();r={'status':'failed','type':type(e).__name__,'message':str(e)[:500],'elapsed_s':time.monotonic()-start,'free_ram':m['availableRamBytes'],'free_commit':m['commitLimitBytes']-m['committedBytes'],'traceback':[{'file':Path(x.filename).name,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(e.__traceback__)]};(out/'failure.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));raise SystemExit(1)
