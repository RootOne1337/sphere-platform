import os,sys,time,pathlib,json,hashlib,subprocess
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-night-sky-audit-20261101');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');G=1024**3
ids=[26,54,92,300,550,801];src=sorted((base/'models/0').glob('*.bin'))+[base/'database.db']+[base/'prepared/images'/f'{i:08d}.png' for i in ids]+[pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png')]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];before={str(p):sha(p) for p in src};(root/'hash-before.json').write_text(json.dumps(before,indent=2));samples=[];reason=None;exitcode=None;start=time.monotonic()
 if min(initial)>=4.5*G:
  env=os.environ.copy();env['PYTHONPATH']=str(pathlib.Path.cwd())+os.pathsep+str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve())
  with (root/'worker.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'work'],stdout=log,stderr=subprocess.STDOUT,env=env)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-start>120:reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.4)
   exitcode=p.returncode
 else:reason='admission_memory'
 after={str(p):sha(p) for p in src};(root/'hash-after.json').write_text(json.dumps(after,indent=2));r={'inputs_unchanged':before==after,'initial_ram':initial[0],'initial_commit':initial[1],'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'exit':exitcode,'stop':reason,'seconds':time.monotonic()-start};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True);sys.exit()
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np,cv2,pycolmap as p,sqlite3
cv2.setNumThreads(2);rec=p.Reconstruction(base/'models/0');ims={im.name:im for im in rec.images.values()}; geom=json.loads((base/'geometry-0.json').read_text());medianstep=float(np.median(np.linalg.norm(np.diff(np.array([r['center'] for r in geom['cameras']]),axis=0),axis=1)));(root/'masks').mkdir(exist_ok=True)
with sqlite3.connect((base/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 kps={i:np.frombuffer(raw,np.float32).reshape(n,c)[:,:2].copy() for i,n,c,raw in db.execute('select image_id,rows,cols,data from keypoints')}
# Hand-inspected HIGH-PRECISION interiors, pixel units at 1920x1080; not segmentation or coverage of entire sky.
sky={26:[[(1000,15),(1270,15),(1270,320),(1000,320)]],54:[[(750,15),(1240,15),(1240,300),(750,300)]],92:[[(320,10),(1300,10),(1300,250),(320,250)]],300:[[(320,10),(1000,10),(1000,280),(320,280)]],550:[[(780,10),(1050,10),(1050,250),(780,250)]],801:[[(330,10),(650,10),(650,140),(330,140)],[(800,10),(1200,10),(1200,140),(800,140)]]}
fac={26:[(550,140),(830,140),(830,450),(550,450)],54:[(320,100),(650,100),(650,450),(320,450)],92:[(1450,160),(1530,160),(1530,350),(1450,350)],300:[(1160,200),(1400,200),(1400,410),(1160,410)],550:[(1200,150),(1450,150),(1450,360),(1200,360)],801:[(800,250),(1150,250),(1150,495),(800,495)]}
def maskpoly(polys):
 m=np.zeros((1080,1920),np.uint8);cv2.fillPoly(m,[np.asarray(poly,np.int32) for poly in polys],255);return m
def summarize(rows):
 if not rows:return {'count':0}
 a=np.asarray(rows);return {'count':len(rows),'depth_units_median':float(np.median(a[:,0])),'depth_in_median_step_median':float(np.median(a[:,0])/medianstep),'max_track_angle_deg_median':float(np.median(a[:,1])),'max_track_angle_deg_p10':float(np.percentile(a[:,1],10)),'reprojection_px_median':float(np.median(a[:,2])),'reprojection_px_p95':float(np.percentile(a[:,2],95)),'track_views_median':float(np.median(a[:,3]))}
contact=[];reports=[]
for i in ids:
 name=f'{i:08d}.png';im=ims[name];img=cv2.imread(str(base/'prepared/images'/name));assert img is not None and img.shape==(1080,1920,3);sm=maskpoly(sky[i]);fm=maskpoly([fac[i]]);cv2.imwrite(str(root/'masks'/name),sm);out=img.copy();out[sm>0]=(0.65*img[sm>0]+0.35*np.array([0,0,230])).astype(np.uint8);rows={'sky_interior':[],'facade_reference':[]};count=0;coords=np.rint(kps[im.image_id]).astype(int);valid=(coords[:,0]>=0)&(coords[:,0]<1920)&(coords[:,1]>=0)&(coords[:,1]<1080);coords=coords[valid];excluded=int(np.count_nonzero(sm[coords[:,1],coords[:,0]]))
 pose=im.cam_from_world();R=pose.rotation.matrix();t=pose.translation;C=im.projection_center();cam=rec.cameras[im.camera_id];f,cx,cy=cam.params
 for pt2 in im.points2D:
  if not pt2.has_point3D():continue
  x,y=map(int,np.rint(pt2.xy));
  if not(0<=x<1920 and 0<=y<1080):continue
  pt=rec.points3D[pt2.point3D_id];P=pt.xyz;q=R@P+t;count+=1;which='sky_interior' if sm[y,x] else 'facade_reference' if fm[y,x] else None
  if which:
   vec=P-C;vec/=np.linalg.norm(vec);angles=[]
   for el in pt.track.elements:
    v=P-rec.images[el.image_id].projection_center();norm=np.linalg.norm(v)
    if norm>1e-12:angles.append(float(np.degrees(np.arccos(np.clip(vec@(v/norm),-1,1)))))
   pred=np.array([f*q[0]/q[2]+cx,f*q[1]/q[2]+cy]);rows[which].append((float(q[2]),max(angles,default=0.),float(np.linalg.norm(pred-pt2.xy)),pt.track.length()));cv2.circle(out,(x,y),4,(0,220,255) if which=='sky_interior' else (255,230,0),-1)
 for poly in sky[i]:cv2.polylines(out,[np.array(poly,np.int32)],True,(0,0,255),3)
 cv2.polylines(out,[np.array(fac[i],np.int32)],True,(255,230,0),3);left=cv2.resize(img,(640,360));right=cv2.resize(out,(640,360));cv2.putText(left,f'frame {i} raw',(12,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2);cv2.putText(right,f'red=sky sample; cyan=facade: {i}',(12,28),cv2.FONT_HERSHEY_SIMPLEX,.62,(255,255,255),2);contact.append(np.hstack((left,right)));reports.append({'source_index':i,'image':name,'candidate_sky_sample_polygons':sky[i],'facade_reference_polygon':fac[i],'excluded_image_fraction':float(np.mean(sm>0)),'database_2d_features':int(len(coords)),'2d_features_inside_sky_sample':excluded,'2d_features_remaining':int(len(coords))-excluded,'3d_observations_total':count,'sky_interior':summarize(rows['sky_interior']),'facade_reference':summarize(rows['facade_reference']),'other_3d_observations':count-len(rows['sky_interior'])-len(rows['facade_reference'])})
cv2.imwrite(str(root/'contact-sheet.jpg'),np.vstack(contact),[cv2.IMWRITE_JPEG_QUALITY,90]);(root/'report.json').write_text(json.dumps({'method':'Manually inspected conservative sample polygons on six real frames, not an automatic sky segmentation; red polygon for suspected sky, cyan polygon facade comparison. Regions left unclassified elsewhere. Full polygons exclude stars and any underlying pixels. No live/production application.','median_camera_step_units':medianstep,'frames':reports,'interpretation':'3D depth, angle, reprojection all derived from disputed same SfM geometry, not true depth or independent scene truth; brightness/near-star labels are hypotheses. Counts refer to final triangulated observations, not independent features.','approved_for_application':False},indent=2));print('processed',len(reports),flush=True)
