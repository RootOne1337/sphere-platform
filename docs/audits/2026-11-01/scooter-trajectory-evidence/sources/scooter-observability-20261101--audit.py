"""Bounded read-only in-sample per-frame 3D observability audit, no solver/GPU."""
import os,sys,time,json,hashlib,threading,ctypes,collections,csv
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='2';os.environ['MKL_NUM_THREADS']='1'
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'.local-pilot/reconstruction-tools/pycolmap-4.2.1'))
from scripts.pilot.resource_guard import windows_memory
started=time.monotonic();stop=threading.Event();minimum_ram=2**63;minimum_commit=2**63
def write(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def check():
 global minimum_ram,minimum_commit
 m=windows_memory();minimum_ram=min(minimum_ram,m['availableRamBytes']);minimum_commit=min(minimum_commit,m['commitLimitBytes']-m['committedBytes'])
 if min(minimum_ram,minimum_commit)<4.5*2**30:raise RuntimeError('host_runtime_4_5GiB')
 if time.monotonic()-started>30:raise RuntimeError('audit_wall_30s')
check()
def watch():
 while not stop.wait(.2):
  try:check()
  except Exception as e:write('refusal.json',dict(reason=str(e),seconds=time.monotonic()-started));os._exit(4)
threading.Thread(target=watch,daemon=True).start()
k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=2 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(sum(bits[:2])))
import numpy as np
import pycolmap as p
from PIL import Image,ImageDraw,ImageFont
PREP=ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/prepared'
MODELS={'SIFT166':PREP.parent/'models/0','DISK166':ROOT/'.local-pilot/scooter-disk-cpu-20261101/models/0'}
prepared=json.loads((PREP/'reconstruction-input.json').read_text('utf-8'));meta={Path(r['image']).name:r for r in prepared['images']}
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
protected=[PREP/'reconstruction-input.json',*[f for path in MODELS.values() for f in path.glob('*.bin')]];before={str(q):sha(q) for q in protected}
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',15);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',12)
def occupancy(xy,width,height):
 if not len(xy):return [0]*16
 xy=np.asarray(xy);inside=np.isfinite(xy).all(1)&(xy[:,0]>=0)&(xy[:,0]<width)&(xy[:,1]>=0)&(xy[:,1]<height);xy=xy[inside]
 cells=np.floor(xy/np.array([width,height])*4).astype(int)
 return np.bincount(cells[:,1]*4+cells[:,0],minlength=16).tolist()
summaries={};allrows={};projections={};contacts=[]
try:
 for label,model in MODELS.items():
  check();rec=p.Reconstruction(model);per_image=collections.defaultdict(list);track_lengths=collections.Counter();all_observations=0
  for pid,point in rec.points3D.items():
   track_lengths[point.track.length()]+=1
   if point.track.length()<3:continue
   xyz=point.xyz.copy()
   if not np.isfinite(xyz).all():raise RuntimeError('point_nonfinite')
   for element in point.track.elements:
    im=rec.image(element.image_id);q=im.point2D(element.point2D_idx)
    if not q.has_point3D() or q.point3D_id!=pid:raise RuntimeError('track_image_reciprocity')
    per_image[im.image_id].append((xyz,q.xy.copy()));all_observations+=1
  rows=[];projections[label]={}
  for im in sorted(rec.images.values(),key=lambda x:x.name):
   camera=im.camera;items=per_image[im.image_id];xyz=np.array([x[0] for x in items],dtype=float).reshape(-1,3);observed=np.array([x[1] for x in items],dtype=float).reshape(-1,2)
   pose=im.cam_from_world();cam=xyz@pose.rotation.matrix().T+pose.translation;positive=np.isfinite(cam).all(1)&(cam[:,2]>0)
   xy=np.asarray(camera.img_from_cam(cam[positive]),dtype=float).reshape(-1,2) if positive.any() else np.zeros((0,2));in_image=np.isfinite(xy).all(1)&(xy[:,0]>=0)&(xy[:,0]<camera.width)&(xy[:,1]>=0)&(xy[:,1]<camera.height)
   residuals=np.linalg.norm(xy-observed[positive],axis=1);projected_grid=occupancy(xy,camera.width,camera.height);observed_grid=occupancy(observed,camera.width,camera.height);source=meta[im.name]
   row=dict(model=label,image_id=im.image_id,name=im.name,source_index=source['source_index'],ticks_90k=source['relative_ticks_90k'],seconds=source['relative_ticks_90k']/90000,valid_3D_observations=len(items),positive_depth_observations=int(positive.sum()),in_image_projected_observations=int(in_image.sum()),observed_grid_occupied=int(np.count_nonzero(observed_grid)),projected_grid_occupied=int(np.count_nonzero(projected_grid)),projected_grid_fraction=float(np.count_nonzero(projected_grid)/16),observed_grid_counts=observed_grid,projected_grid_counts=projected_grid,median_reprojection_px=float(np.median(residuals)) if len(residuals) else None)
   rows.append(row);projections[label][im.name]=xy[in_image]
  values=np.array([r['valid_3D_observations'] for r in rows]);grids=np.array([r['projected_grid_occupied'] for r in rows]);weak=sorted(rows,key=lambda r:(r['valid_3D_observations'],r['source_index']))
  summaries[label]=dict(model_path=str(model.relative_to(ROOT)),registered=rec.num_reg_images(),model_points3D=rec.num_points3D(),eligible_tracks=sum(n for length,n in track_lengths.items() if length>=3),observations=int(values.sum()),min=int(values.min()),median=float(np.median(values)),p10=float(np.percentile(values,10)),count_under_6=int((values<6).sum()),count_under_15=int((values<15).sum()),grid_occupied_min=int(grids.min()),grid_occupied_median=float(np.median(grids)),grid_occupied_p10=float(np.percentile(grids,10)),weak_frames_under_15=[r for r in weak if r['valid_3D_observations']<15],least_supported_10=weak[:10])
  allrows[label]=rows
  # Three low-support examples separated in source time, plus a strong control.
  selected=[]
  for row in weak:
   if all(abs(row['seconds']-other['seconds'])>=1. for other in selected):selected.append(row)
   if len(selected)==3:break
  control=max(rows,key=lambda r:(r['projected_grid_occupied'],r['valid_3D_observations']));selected.append(control)
  for rank,row in enumerate(selected):
   path=PREP/'images'/row['name']
   if sha(path)!=meta[row['name']]['png_sha256']:raise RuntimeError('source_png_changed')
   image=Image.open(path).convert('RGB').resize((640,360),Image.Resampling.LANCZOS);panel=Image.new('RGB',(640,426),(13,18,28));panel.paste(image,(0,66));draw=ImageDraw.Draw(panel)
   draw.text((8,5),f'{label} {"LOW SUPPORT" if rank<3 else "CONTROL"}  {row["name"]}  PTS {row["ticks_90k"]} ({row["seconds"]:.3f}s)',font=font,fill='white')
   draw.text((8,27),f'3D track>=3 obs={row["valid_3D_observations"]}; projected grid={row["projected_grid_occupied"]}/16; reproj={row["median_reprojection_px"]:.2f}px',font=small,fill=(220,220,220))
   draw.text((8,45),'IN-SAMPLE: yellow crosses = this model\'s tracked 3D projections only',font=small,fill=(255,220,90))
   for q in range(1,4):draw.line((q*160,66,q*160,426),fill=(120,120,120),width=1);draw.line((0,66+q*90,640,66+q*90),fill=(120,120,120),width=1)
   for x,y in projections[label][row['name']]:
    x=x/3-.5;y=y/3-.5+66;draw.line((x-2,y,x+2,y),fill=(255,220,0),width=1);draw.line((x,y-2,x,y+2),fill=(255,220,0),width=1)
   panel.save(OUT/f'{label}-{rank}-{row["name"]}');contacts.append((label,rank,panel,row))
  check()
 sheet=Image.new('RGB',(1280,426*4),(13,18,28))
 for label,rank,panel,row in contacts:sheet.paste(panel,(0 if label=='SIFT166' else 640,rank*426))
 sheet.save(OUT/'contact-sheet.png')
 with (OUT/'per-frame.csv').open('w',newline='',encoding='utf-8') as f:
  keys=[k for k in allrows['SIFT166'][0] if not isinstance(allrows['SIFT166'][0][k],list)];writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
  for rows in allrows.values():writer.writerows({k:r[k] for k in keys} for r in rows)
 after={str(q):sha(q) for q in protected}
 if before!=after:raise RuntimeError('source_model_changed')
 report=dict(status='complete_read_only_in_sample_observability_audit',source_manifest_sha256=prepared['source_manifest_sha256'],definition='Count only reciprocal image observations belonging to actual model Point3D tracks of length >=3; project only those same observed 3D points into that image using actual model pose/intrinsics. Never project unrelated cloud points or raw matches.',models=summaries,per_frame=allrows,contact_examples=[{k:r[k] for k in ('model','name','ticks_90k','seconds','valid_3D_observations','projected_grid_occupied')} for label,rank,panel,r in contacts],protected_hashes=before,protected_sources_unchanged=True,contact_sheet='contact-sheet.png',wall_seconds=time.monotonic()-started,min_available_RAM_GiB=minimum_ram/2**30,min_commit_headroom_GiB=minimum_commit/2**30,CPU_affinity_processors=2,GPU_initialized=False,solver_executed=False,independent_pose_truth=False,executionQualified=False,physicalActions=0)
 write('observability.json',report);print(json.dumps({label:{k:v for k,v in r.items() if k not in ('weak_frames_under_15','least_supported_10')} for label,r in summaries.items()}))
finally:stop.set()
