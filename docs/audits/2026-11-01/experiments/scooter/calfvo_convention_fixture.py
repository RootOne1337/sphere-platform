"""CPU-only algebra fixture using extracted upstream aggregation and pycolmap."""
import os,sys,json,ast,hashlib
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';sys.path.insert(0,os.getcwd());sys.path.insert(0,str(Path('.local-pilot/route-fusion-runtime').resolve()));sys.path.insert(0,str(Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,pycolmap as p
from scipy.spatial.transform import Rotation as R
src=Path('.local-pilot/reconstruction-tools/calfvo-64497981704a/src/utils/training_utils.py');tree=ast.parse(src.read_text(encoding='utf8'))
functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('average_SE3','recover_trajectory')];assert len(functions)==2
env={'np':np,'R':R};exec(compile(ast.Module(body=functions,type_ignores=[]),str(src),'exec'),env)
R1=R.from_euler('z',38,degrees=True).as_matrix();R2=R.from_euler('y',-23,degrees=True).as_matrix()
T01=np.eye(4);T01[:3,:3]=R1;T01[:3,3]=[1,2,3]
T12=np.eye(4);T12[:3,:3]=R2;T12[:3,3]=[-.5,.3,1]
actual=env['recover_trajectory'](np.stack([T01,T12]),np.array([[0,1,2]]),np.ones((2,2)))
expected=np.stack([np.eye(4),T01,T01@T12]);assert np.allclose(actual,expected,atol=1e-12)
Twc=actual[-1];Rcw=Twc[:3,:3].T;tcw=-Rcw@Twc[:3,3];points_cam=np.array([[0.,0.,5.],[1.,0.,5.],[0.,1.,5.],[-.4,.7,4.]])
points_world=(Twc[:3,:3]@points_cam.T).T+Twc[:3,3]
manual=(Rcw@points_world.T).T+tcw;assert np.allclose(manual,points_cam)
pose=p.Rigid3d(p.Rotation3d(Rcw),tcw);pc=pose*points_world;assert np.allclose(pc,points_cam)
camera=p.Camera(model='SIMPLE_PINHOLE',width=1920,height=1080,params=[960.,960.,540.]);pixels=camera.img_from_cam(pc)
formula=np.stack([960*pc[:,0]/pc[:,2]+960,960*pc[:,1]/pc[:,2]+540],axis=1)
assert np.allclose(pixels,formula) and pixels[1,0]>pixels[0,0] and pixels[2,1]>pixels[0,1]
assert camera.img_from_cam(np.array([0.,0.,-1.])) is None
q=p.Rotation3d(Rcw).quat; q_colmap=[q[3],q[0],q[1],q[2]]; roundtrip=p.Rotation3d(np.array([q_colmap[1],q_colmap[2],q_colmap[3],q_colmap[0]])).matrix();assert np.allclose(roundtrip,Rcw)
candidate=Path('.local-pilot/scooter-calfvo-full-20261101/candidate.npz');d=np.load(candidate);poses=d['trajectory_c2w'];idx=d['frame_indices'];ticks=d['ticks_90k'];assert len(poses)==len(idx)==len(ticks)==901 and np.array_equal(idx,np.arange(901)) and np.allclose(poses[0],np.eye(4))
recovered=env['recover_trajectory'](d['relative_poses'],d['window_frame_ids'],d['confidence']);diff=float(np.max(np.abs(recovered-poses)));assert diff<1e-10
rotations=poses[:,:3,:3];orth=np.linalg.norm(rotations.transpose(0,2,1)@rotations-np.eye(3),axis=(1,2));dets=np.linalg.det(rotations)
rows={'fixture':'passed','upstream_functions':'training_utils.py average_SE3 and recover_trajectory extracted unchanged via AST','relative_pose_formula':'inv(T_world_camera_i) @ T_world_camera_j','composition':'T_world_camera_j = T_world_camera_i @ T_i_j','colmap_cam_from_world':'R_cw = R_wc.T, t_cw = -R_cw @ t_wc','quaternion':'pycolmap XYZW converted to COLMAP text WXYZ and back','projection':'x=f X/Z+cx; y=f Y/Z+cy; positive Z; pycolmap agrees','fixture_max_pixel_error':float(np.max(abs(pixels-formula))),'candidate_frames':len(poses),'candidate_first_identity':True,'candidate_tick_strict_increasing':bool(np.all(np.diff(ticks)>0)),'max_candidate_vs_upstream_reaggregation_abs':diff,'max_rotation_orthogonality_frobenius_error':float(orth.max()),'rotation_determinant_min':float(dets.min()),'rotation_determinant_max':float(dets.max()),'limitations':'This proves algebra and adapter mechanics for a synthetic CV camera, not that model output axes match the game camera or that inferred poses are accurate. CROCO/DINO training includes heterogeneous datasets; no independently measured game-camera extrinsics. Intrinsics and mask are separate unresolved assumptions.'}
out=Path('.local-pilot/scooter-calfvo-convention-audit-20261101');(out/'fixture.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2))
