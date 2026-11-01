"""Prepared isolated 3-frame SIFT/LG pipeline. Run only after source handoff."""
import os,sys,time,pathlib,json,sqlite3,hashlib,subprocess
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-temporal-bridge-20261101');prep=root/'prepared';stage=pathlib.Path('.local-pilot/scooter-stage-isolation-20261101');target=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');baseline=pathlib.Path('.local-pilot/scooter-temporal-flow-full-20261101/filtered-verified-as-new-raw.db');mask=pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png');G=1024**3;newnames=[f'{i:08d}.png' for i in (501,502,503)]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def rawhash(path):
 h=hashlib.sha256();count=0
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
  for pid,n,c,blob in db.execute('select pair_id,rows,cols,data from matches order by pair_id'):
   i,j=divmod(pid,2147483647)
   if i<=166 and j<=166:h.update(f'{pid}:{n}:{c}:'.encode());h.update(blob or b'');count+=1
 return {'count':count,'sha256':h.hexdigest()}
if len(sys.argv)==1:
 sources=[baseline,mask,prep/'reconstruction-input.json',stage/'stage1-receipt.json',target/'prepare-receipt.json']+[prep/'images'/n for n in newnames];before={str(p):sha(p) for p in sources};(root/'features-input-hash-before.json').write_text(json.dumps(before,indent=2));m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples=[];runs=[];stop=None;start=time.monotonic()
 if min(initial)>=6.5*G:
  for name,venv,limit in [('features','motor-worker-venv',90),('match','motor-amd-venv',90)]:
   env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(pathlib.Path.cwd()),str(pathlib.Path('.local-pilot/'+venv+'/Lib/site-packages').resolve()),str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())]);t=time.monotonic();stop=None
   with (root/(name+'.log')).open('w') as log:
    child=subprocess.Popen([sys._base_executable,str(pathlib.Path(__file__).resolve()),name],stdout=log,stderr=subprocess.STDOUT,env=env)
    while child.poll() is None:
     m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
     if min(v)<4.5*G or time.monotonic()-t>limit:stop='memory_guard' if min(v)<4.5*G else 'timeout';child.kill();child.wait();break
     time.sleep(.4)
    code=child.returncode
   runs.append({'stage':name,'exit':code,'stop':stop,'seconds':time.monotonic()-t});(root/'feature-match-progress.json').write_text(json.dumps(runs,indent=2));print(runs[-1],flush=True)
   if code!=0 or stop:break
 else:stop='admission_memory'
 after={str(p):sha(p) for p in sources};(root/'features-input-hash-after.json').write_text(json.dumps(after,indent=2));receipt={'inputs_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'runs':runs,'stop':stop,'seconds':time.monotonic()-start,'only_owned_direct_child':True};(root/'feature-match-receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True);sys.exit()
stage_name=sys.argv[1]
if stage_name=='features':
 from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
 initialize_route_cpu_runtime()
 import cv2,numpy as np,pycolmap as p
 cv2.setNumThreads(2);metadata=json.loads((prep/'reconstruction-input.json').read_text());rows={pathlib.Path(r['image']).name:r for r in metadata['images']};assert len(rows)==169 and set(newnames)<=rows.keys();(root/'cache').mkdir(exist_ok=True);prec=cv2.imread(str(mask),0);assert prec.shape==(1080,1920);prec[int(1080*.975):]=0;sift=cv2.SIFT_create(nfeatures=8192,contrastThreshold=.0066667,edgeThreshold=10);features={}
 for name in newnames:
  row=rows[name];path=prep/'images'/name;assert sha(path)==row['png_sha256'];gray=cv2.imread(str(path),0);kp,desc=sift.detectAndCompute(gray,prec);assert desc is not None and len(kp)>=15;detected=len(kp)
  if len(kp)>4096:
   keep=sorted(range(len(kp)),key=lambda j:(-kp[j].response,j))[:4096];kp=[kp[j] for j in keep];desc=desc[keep]
  xy=np.asarray([k.pt for k in kp],np.float32)+.5;scales=np.asarray([k.size for k in kp],np.float32);angles=np.deg2rad(np.asarray([k.angle for k in kp],np.float32));desc/=np.maximum(desc.sum(-1,keepdims=True),1e-6);desc=np.sqrt(np.maximum(desc,1e-6));desc/=np.maximum(np.linalg.norm(desc,axis=-1,keepdims=True),1e-6);data={'keypoints':xy,'scales':scales,'oris':angles,'descriptors':desc,'image_size':np.array([1920,1080],np.float32)};file=root/'cache'/(name+'.npz');np.savez(file,**data);features[name]={'count':len(kp),'detected':detected,'cache_sha256':sha(file),'png_sha256':row['png_sha256']}
 with sqlite3.connect(baseline.resolve().as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(root/'features-raw.db') as b:a.backup(b)
 before=rawhash(baseline);assert before['count']==807 and rawhash(root/'features-raw.db')==before
 with p.Database.open(root/'features-raw.db') as db:old={im.name:im.image_id for im in db.read_all_images()};assert len(old)==166;camera_ids={im.camera_id for im in db.read_all_images()};assert len(camera_ids)==1;cid=next(iter(camera_ids))
 p.import_images(root/'features-raw.db',prep/'images',camera_mode=p.CameraMode.SINGLE,image_names=newnames,options=p.ImageReaderOptions(camera_model='SIMPLE_PINHOLE',existing_camera_id=cid))
 with p.Database.open(root/'features-raw.db') as db:
  images={im.name:im for im in db.read_all_images()};assert len(images)==169 and all(images[k].image_id==v for k,v in old.items());assert {images[n].image_id for n in newnames}=={167,168,169}
  for name in newnames:
   with np.load(root/'cache'/(name+'.npz'),allow_pickle=False) as z:db.write_keypoints(images[name].image_id,np.column_stack([z['keypoints'],z['scales'],z['oris']]));db.write_descriptors(images[name].image_id,p.FeatureDescriptors(p.FeatureExtractorType.SIFT,np.clip(np.round(z['descriptors']*512),0,255).astype('uint8')))
 (root/'features-receipt.json').write_text(json.dumps({'new_features':features,'old_raw_pairs':before,'selected':169,'baseline_unchanged':rawhash(baseline)==before},indent=2));print('three features ready',flush=True)
elif stage_name=='match':
 import socket
 def deny(*a,**kw):raise RuntimeError('network_disabled')
 socket.socket.connect=deny;socket.create_connection=deny
 import numpy as np,torch,pycolmap as p
 from collections import OrderedDict
 from scripts.pilot.learned_route_features import load_matcher
 torch.set_num_threads(2);assert torch.cuda.is_available();free,total=torch.cuda.mem_get_info();assert free>=8*G,(free,total);torch.cuda.reset_peak_memory_stats();matcher=load_matcher(pathlib.Path.cwd(),memory_fraction=min(3*G,total)/total,device='cuda');assert not matcher.conf.mp
 existing=json.loads((stage/'stage1-receipt.json').read_text())['files'];oldnew=json.loads((target/'prepare-receipt.json').read_text())['new'];fresh=json.loads((root/'features-receipt.json').read_text())['new_features'];lru=OrderedDict();used={}
 def get(name):
  if name in lru:lru.move_to_end(name);return lru[name]
  if name in newnames:file=root/'cache'/(name+'.npz');expected=fresh[name]['cache_sha256']
  elif int(name[:-4]) in (497,498,499):file=target/'cache'/(name+'.npz');expected=oldnew[str(int(name[:-4]))]['cache_sha256']
  else:file=stage/'cache'/(name+'.npz');expected=existing[name]['cache_sha256']
  assert sha(file)==expected;used[name]=expected
  with np.load(file,allow_pickle=False) as z:data={k:torch.from_numpy(z[k])[None] for k in z.files}
  lru[name]=data
  if len(lru)>2:lru.popitem(last=False)
  return data
 result=[]
 with p.Database.open(root/'features-raw.db') as db:
  images={im.name:im for im in db.read_all_images()};assert len(images)==169;metadata=json.loads((prep/'reconstruction-input.json').read_text());ticks={pathlib.Path(r['image']).name:r['relative_ticks_90k'] for r in metadata['images']};anchors=[f'{i:08d}.png' for i in (497,498,499,500,504,509,515)];assert all(n in images for n in anchors);edges={tuple(sorted((a,b))) for a in newnames for b in anchors};edges.update((newnames[i],newnames[j]) for i in range(3) for j in range(i+1,3));assert len(edges)==24 and all(abs(ticks[a]-ticks[b])<=90000 for a,b in edges)
  with torch.inference_mode():
   for aa,bb in sorted(edges):
    a,b=(aa,bb) if images[aa].image_id<images[bb].image_id else (bb,aa);x=get(a);y=get(b);xx={k:v.to('cuda') for k,v in x.items()};yy={k:v.to('cuda') for k,v in y.items()};o=matcher({'image0':xx,'image1':yy});mat=o['matches'][0].cpu().numpy().astype('uint32');assert mat.ndim==2 and mat.shape[1]==2 and len(mat)<=4096;db.write_matches(images[a].image_id,images[b].image_id,mat);result.append({'first':a,'second':b,'matches':len(mat)});del o,xx,yy,x,y
    m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*G;assert torch.cuda.max_memory_reserved()<=3*G
 gpu={'free_before':free,'total':total,'cap':3*G,'peak_reserved':torch.cuda.max_memory_reserved(),'peak_allocated':torch.cuda.max_memory_allocated()};del matcher;lru.clear();torch.cuda.empty_cache();assert rawhash(root/'features-raw.db')==rawhash(baseline);(root/'new-pairs.txt').write_text(''.join(x['first']+' '+x['second']+'\n' for x in result));(root/'match-receipt.json').write_text(json.dumps({'new_pairs':len(result),'rows':result,'old_raw_pairs_unchanged':True,'used_cache_hashes':used,'gpu':gpu,'status':'matching_complete_not_flow_filtered'},indent=2));print('new pairs',len(result),flush=True)
else:raise SystemExit('Unsupported stage')
