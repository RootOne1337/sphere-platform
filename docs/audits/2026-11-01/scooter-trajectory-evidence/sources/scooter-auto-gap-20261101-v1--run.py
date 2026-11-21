import os,sys,json,time,pathlib,subprocess,hashlib,sqlite3
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',HF_HUB_OFFLINE='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-auto-gap-20261101-v1');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');stage=pathlib.Path('.local-pilot/scooter-stage-isolation-20261101');orig=base/'prepared';mask=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png');job=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');G=1024**3
inputs=[job/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[base/'database.db',base/'report.json',base/'geometry-0.json',base/'prepare-receipt.json',orig/'reconstruction-input.json',stage/'stage1-receipt.json',root/'plan.json',mask]+list(sorted((base/'cache').glob('*.npz')))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def matchdigest(dbpath):
 h=hashlib.sha256()
 with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as c:
  for pair,n,col,data in c.execute('select pair_id,rows,cols,data from matches order by pair_id'):
   h.update(f'{pair}:{n}:{col}:'.encode());h.update(data or b'')
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in inputs};(root/'hash-before.json').write_text(json.dumps(before,indent=2));t0=time.monotonic();runs=[];samples=[];m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];reason=None
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())
  for name,python,limit in [('prepare','.local-pilot/motor-worker-venv/Scripts/python.exe',90),('match','.local-pilot/motor-amd-venv/Scripts/python.exe',90),('map','.local-pilot/motor-worker-venv/Scripts/python.exe',120)]:
   start=time.monotonic();reason=None
   if start-t0>=240:runs.append({'stage':name,'stop':'total_deadline'});break
   with (root/(name+'.log')).open('w') as log:
    p=subprocess.Popen([str(pathlib.Path(python).resolve()),str(pathlib.Path(__file__).resolve()),name],stdout=log,stderr=subprocess.STDOUT,env=env)
    while p.poll() is None:
     m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
     if min(v)<4.5*G or time.monotonic()-t0>240 or time.monotonic()-start>limit:
      reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
     time.sleep(.5)
    code=p.returncode
   runs.append({'stage':name,'exit':code,'stop':reason,'seconds':time.monotonic()-start});(root/'progress.json').write_text(json.dumps(runs,indent=2));print(runs[-1],flush=True)
   if code!=0 or reason:break
 else:reason='admission_memory'
 after={str(p):sha(p) for p in inputs};(root/'hash-after.json').write_text(json.dumps(after,indent=2));out={'initial_ram':initial[0],'initial_commit':initial[1],'stages':runs,'admission_stop':reason if not runs else None,'seconds':time.monotonic()-t0,'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'inputs_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True);sys.exit()
name=sys.argv[1];prepared=root/'prepared';plan=json.loads((root/'plan.json').read_text());added=plan['added_indices'];newset={f'{i:08d}.png' for i in added}
if name=='prepare':
 from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
 initialize_route_cpu_runtime()
 import cv2,numpy as np,shutil
 from PIL import Image
 from motor_worker.browser_teach import validate_browser,decoded_browser
 from scripts.pilot.route_overlap_sampling import plan_pose_gaps
 cv2.setNumThreads(2);prepared.mkdir();(prepared/'images').mkdir();(root/'cache').mkdir();meta=json.loads((orig/'reconstruction-input.json').read_text());rows=meta['images'];frames=[json.loads(x) for x in (job/'frames.jsonl').read_text().splitlines()];initial=[x['source_index'] for x in rows];bindings=[{'image':pathlib.Path(x['image']).name,'source_index':x['source_index'],'relative_ticks_90k':x['relative_ticks_90k']} for x in rows];motion=json.loads((base/'report.json').read_text())['models'][0]['motion'];assert plan==plan_pose_gaps(frames,initial,bindings,motion,max_additions=24,max_selected=240);assert len(rows)==166 and 0<len(added)<=24 and not set(added)&set(initial)
 capture=validate_browser(job);assert sha(job/'manifest.json')==meta['source_manifest_sha256'];new={};oldchecks={};expected={r['source_index']:r for r in rows};reference={i for z in plan['intervals'] for i in (z['first_index'],z['second_index'])}
 for row,frame in decoded_browser(capture):
  i=row['index']
  if i in reference:
   ref=cv2.imread(str(orig/expected[i]['image']));rgb=frame.to_ndarray(format='rgb24');oldchecks[i]=bool(np.array_equal(cv2.cvtColor(ref,cv2.COLOR_BGR2RGB),rgb))
  if i in added:
   rgb=frame.to_ndarray(format='rgb24');filename=f'{i:08d}.png';p=prepared/'images'/filename;Image.fromarray(rgb).save(p);new[i]={'image':'images/'+filename,'source_index':i,'relative_ticks_90k':row['relative_ticks_90k'],'worker_observed_at_ms':row['worker_observed_at_ms'],'source_access_unit_sha256':row['sha256'],'png_sha256':sha(p),'bytes':p.stat().st_size}
 assert set(new)==set(added) and set(oldchecks)==reference and all(oldchecks.values())
 for r in rows:
  source=orig/r['image'];assert sha(source)==r['png_sha256'];shutil.copyfile(source,prepared/r['image']);assert sha(prepared/r['image'])==r['png_sha256']
 meta['images']=sorted(rows+list(new.values()),key=lambda x:x['source_index']);meta['selection']='automatic_pose_gap_iteration';meta['sampling']={'method':'plan_pose_gaps','prior_views':len(initial),'added_source_indices':added,'no_interpolation':True};meta['prepared_bytes']=sum(x['bytes'] for x in meta['images']);(prepared/'reconstruction-input.json').write_text(json.dumps(meta,indent=2));
 prec=cv2.imread(str(mask),0);prec[int(1080*.975):]=0;sift=cv2.SIFT_create(nfeatures=8192,contrastThreshold=.0066667,edgeThreshold=10);features={}
 for i,r in new.items():
  gray=cv2.imread(str(prepared/r['image']),0);kp,desc=sift.detectAndCompute(gray,prec);assert desc is not None and len(kp)>=15
  if len(kp)>4096:
   keep=sorted(range(len(kp)),key=lambda j:(-kp[j].response,j))[:4096];kp=[kp[j] for j in keep];desc=desc[keep]
  xy=np.asarray([k.pt for k in kp],dtype='float32')+.5;scales=np.asarray([k.size for k in kp],dtype='float32');angles=np.deg2rad(np.asarray([k.angle for k in kp],dtype='float32'));desc/=np.maximum(desc.sum(-1,keepdims=True),1e-6);desc=np.sqrt(np.maximum(desc,1e-6));desc/=np.maximum(np.linalg.norm(desc,axis=-1,keepdims=True),1e-6);data={'keypoints':xy,'scales':scales,'oris':angles,'descriptors':desc,'image_size':np.array([1920,1080],dtype='float32')};p=root/'cache'/f'{i:08d}.png.npz';np.savez(p,**data);features[str(i)]={'png_sha256':r['png_sha256'],'source_access_unit_sha256':r['source_access_unit_sha256'],'ticks_90k':r['relative_ticks_90k'],'features':len(kp),'cache_sha256':sha(p)}
 with sqlite3.connect((base/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(root/'database.db') as b:a.backup(b)
 assert matchdigest(root/'database.db')==matchdigest(base/'database.db');(root/'prepare-receipt.json').write_text(json.dumps({'new':features,'original_views':len(initial),'new_views':len(new),'pixel_reference_matches':oldchecks,'source_complete_decode':True,'old_raw_matches_sha256':matchdigest(base/'database.db')},indent=2));print('prepared',len(new),'old',len(initial),flush=True)
elif name=='match':
 import socket
 def deny(*a,**kw):raise RuntimeError('network_disabled')
 socket.socket.connect=deny;socket.create_connection=deny
 import numpy as np,torch,pycolmap as p
 from collections import OrderedDict
 from scripts.pilot.learned_route_features import load_matcher
 torch.set_num_threads(2);s1=json.loads((stage/'stage1-receipt.json').read_text());original=s1['files'];previous=json.loads((base/'prepare-receipt.json').read_text())['new'];new=json.loads((root/'prepare-receipt.json').read_text())['new'];names=sorted(newset);dbpath=root/'database.db'
 with p.Database.open(dbpath) as db:old={x.name:x.image_id for x in db.read_all_images()};assert len(old)==166;camera_ids={x.camera_id for x in db.read_all_images()};assert len(camera_ids)==1;cid=next(iter(camera_ids))
 p.import_images(dbpath,prepared/'images',camera_mode=p.CameraMode.SINGLE,image_names=names,options=p.ImageReaderOptions(camera_model='SIMPLE_PINHOLE',existing_camera_id=cid))
 with p.Database.open(dbpath) as db:
  allimages={x.name:x for x in db.read_all_images()};assert len(allimages)==len(plan['selected_indices']) and all(allimages[k].image_id==v for k,v in old.items()) and all(x.camera_id==cid for x in allimages.values())
  for n in names:
   z=np.load(root/'cache'/(n+'.npz'),allow_pickle=False);xy=z['keypoints'];scales=z['scales'];angles=z['oris'];desc=z['descriptors'];db.write_keypoints(allimages[n].image_id,np.column_stack([xy,scales,angles]));db.write_descriptors(allimages[n].image_id,p.FeatureDescriptors(p.FeatureExtractorType.SIFT,np.clip(np.round(desc*512),0,255).astype('uint8')));z.close()
  ordered=sorted(allimages);edges=set()
  for j,a in enumerate(ordered):
   for lag in (1,2,3,5,8):
    if j+lag<len(ordered):
     b=ordered[j+lag]
     if a in newset or b in newset:edges.add((a,b))
  lru=OrderedDict();used={}
  def get(n):
   if n in lru:lru.move_to_end(n);return lru[n]
   if n in newset:file=root/'cache'/(n+'.npz');expected=new[str(int(n[:-4]))]['cache_sha256']
   elif n in original:file=stage/'cache'/(n+'.npz');expected=original[n]['cache_sha256']
   else:file=base/'cache'/(n+'.npz');expected=previous[str(int(n[:-4]))]['cache_sha256']
   assert sha(file)==expected;used[n]=expected
   with np.load(file,allow_pickle=False) as z:d={k:torch.from_numpy(z[k])[None] for k in z.files}
   lru[n]=d
   if len(lru)>2:lru.popitem(last=False)
   return d
  if not torch.cuda.is_available():raise RuntimeError('gpu_unavailable')
  free,total=torch.cuda.mem_get_info();assert free>=5*G;matcher=load_matcher(pathlib.Path.cwd(),memory_fraction=min(3*G,total)/total,device='cuda');torch.set_num_threads(2);assert not matcher.conf.mp
  result=[]
  with torch.inference_mode():
   for aa,bb in sorted(edges):
    a,b=(aa,bb) if allimages[aa].image_id<allimages[bb].image_id else (bb,aa);x=get(a);y=get(b);xx={k:v.to('cuda') for k,v in x.items()};yy={k:v.to('cuda') for k,v in y.items()};o=matcher({'image0':xx,'image1':yy});mat=o['matches'][0].cpu().numpy().astype('uint32');assert mat.ndim==2 and mat.shape[1]==2 and len(mat)<=4096;db.write_matches(allimages[a].image_id,allimages[b].image_id,mat);result.append({'first':a,'second':b,'matches':len(mat)});del o,xx,yy,x,y
    m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*G
  gpu={'free_before':free,'total':total,'cap':3*G,'peak_allocated':torch.cuda.max_memory_allocated(),'peak_reserved':torch.cuda.max_memory_reserved()};del matcher;lru.clear();torch.cuda.empty_cache()
 pairfile=root/'new-pairs.txt';pairfile.write_text(''.join(r['first']+' '+r['second']+'\n' for r in result));oldids=set(old.values());h=hashlib.sha256();count=0
 with sqlite3.connect(dbpath) as c:
  for pid,n,col,raw in c.execute('select pair_id,rows,cols,data from matches order by pair_id'):
   a,b=divmod(pid,2147483647)
   if a in oldids and b in oldids:h.update(f'{pid}:{n}:{col}:'.encode());h.update(raw or b'');count+=1
 assert count==823 and h.hexdigest()==json.loads((root/'prepare-receipt.json').read_text())['old_raw_matches_sha256'];(root/'match-receipt.json').write_text(json.dumps({'old_raw_pairs_unchanged':True,'old_raw_pairs':count,'new_pairs':len(result),'new_pair_details':result,'cache_used_hashes':used,'gpu':gpu,'graph_contract':'preserve all previous raw and verified; add only edges incident to automatically selected new real frames'},indent=2));print('new pairs',len(result),'old preserved',flush=True)
elif name=='map':
 import ctypes
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=ctypes.c_void_p;k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];proc=k.GetCurrentProcess();pm=ctypes.c_size_t();sm=ctypes.c_size_t();assert k.GetProcessAffinityMask(proc,ctypes.byref(pm),ctypes.byref(sm));bits=[1<<i for i in range(64) if pm.value&(1<<i)];assert len(bits)>=2 and k.SetProcessAffinityMask(proc,ctypes.c_size_t(bits[0]|bits[1]));
 from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
 initialize_route_cpu_runtime()
 import pycolmap as p
 dbpath=root/'database.db';opts=p.TwoViewGeometryOptions();opts.ransac.num_threads=1;opts.filter_stationary_matches=False;p.verify_matches(dbpath,root/'new-pairs.txt',options=opts)
 with sqlite3.connect(dbpath) as c:counts={'raw':c.execute('select count(*) from matches').fetchone()[0],'verified_nonempty':c.execute('select count(*) from two_view_geometries where rows>0').fetchone()[0]}
 (root/'verification.json').write_text(json.dumps(counts,indent=2));print('verified',counts,flush=True)
 with p.Database.open(dbpath) as db:
  cams=db.read_all_cameras();assert len(cams)==1;cam=cams[0];cam.params=[604.4325003117685,960.,540.];cam.has_prior_focal_length=True;db.update_camera(cam)
 assert p.calibrate_view_graph(dbpath,p.ViewGraphCalibrationOptions(random_seed=17))
 o=p.GlobalPipelineOptions(num_threads=2,random_seed=17,ignore_watermarks=True);o.mapper.num_threads=2;o.mapper.refine_sensor_from_rig=False;o.mapper.global_positioning.use_gpu=False;o.mapper.global_positioning.refine_sensor_from_rig=False;o.mapper.rotation_averaging.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_sensor_from_rig=False;o.mapper.bundle_adjustment.refine_focal_length=True;o.mapper.bundle_adjustment.refine_extra_params=False;o.mapper.bundle_adjustment.ceres.use_gpu=False;o.mapper.bundle_adjustment.ceres.solver_options.num_threads=2;o.mapper.bundle_adjustment.ceres.solver_options.max_num_iterations=30;o.mapper.keep_max_num_tracks=30000
 modelsdir=root/'models';modelsdir.mkdir();models=p.global_mapping(dbpath,prepared/'images',modelsdir,options=o)
 from scripts.pilot.reconstruct_route import model_assessment
 reports=[]
 for identity,rec in models.items():
  if rec.num_reg_images()<2 or not rec.num_points3D():reports.append({'model':identity,'registered':rec.num_reg_images(),'points':rec.num_points3D(),'reason':'insufficient_geometry'});continue
  geom,report=model_assessment(rec,prepared,len(plan['selected_indices']),0.,35.493);reports.append(dict(model=identity,**report));(root/f'geometry-{identity}.json').write_text(json.dumps(geom))
 (root/'report.json').write_text(json.dumps({'models':reports,'camera':'shared SIMPLE_PINHOLE f604.4325 initial refined','no_autoaccept':True,'physical_calibration_verified':False},indent=2));print('components',len(models),flush=True)
