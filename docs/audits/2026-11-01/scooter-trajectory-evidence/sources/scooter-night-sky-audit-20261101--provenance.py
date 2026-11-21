import os,sys,pathlib,json,sqlite3,hashlib
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import cv2,numpy as np,pycolmap as p
cv2.setNumThreads(2);root=pathlib.Path('.local-pilot/scooter-night-sky-audit-20261101');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*1024**3
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
source=sorted((base/'models/0').glob('*.bin'))+[base/'database.db',pathlib.Path('.local-pilot/scooter-precise-hud-20261101/mask.png')];before={str(f):sha(f) for f in source};report=json.loads((root/'report.json').read_text());rec=p.Reconstruction(base/'models/0');images={i.name:i for i in rec.images.values()};sift=cv2.SIFT_create(nfeatures=8192,contrastThreshold=.0066667,edgeThreshold=10);mask=cv2.imread('.local-pilot/scooter-precise-hud-20261101/mask.png',0);mask[int(1080*.975):]=0;items=[]
with sqlite3.connect((base/'database.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
 raw=list(db.execute('select pair_id,rows,cols,data from matches where rows>0'));verified=list(db.execute('select pair_id,rows,cols,data from two_view_geometries where rows>0'))
 for entry in report['frames']:
  m=windows_memory();assert min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])>=4.5*1024**3
  name=entry['image'];im=images[name];iid=im.image_id;dbrow=db.execute('select rows,cols,data from keypoints where image_id=?',(iid,)).fetchone();n,cols,blob=dbrow;xy=np.frombuffer(blob,np.float32).reshape(n,cols)[:,:2];sky=cv2.imread(str(root/'masks'/name),0)>0;ij=np.rint(xy).astype(int);inbounds=(ij[:,0]>=0)&(ij[:,0]<1920)&(ij[:,1]>=0)&(ij[:,1]<1080);issky=np.zeros(n,bool);issky[inbounds]=sky[ij[inbounds,1],ij[inbounds,0]]
  def unique(rows):
   result=set()
   for pair_id,nrows,ncols,data in rows:
    a,b=divmod(pair_id,2147483647)
    if iid not in (a,b):continue
    values=np.frombuffer(data,np.uint32).reshape(nrows,ncols)[:,0 if iid==a else 1];result.update(map(int,values))
   return result
  rawids=unique(raw);verifiedids=unique(verified);assert max(rawids|verifiedids,default=0)<n;fin=set();reciprocal=set()
  assert im.num_points2D()==n
  for idx,feature in enumerate(im.points2D):
   if feature.has_point3D():
    fin.add(idx);pt=rec.points3D[feature.point3D_id]
    if any(e.image_id==iid and e.point2D_idx==idx for e in pt.track.elements):reciprocal.add(idx)
  gray=cv2.imread(str(base/'prepared/images'/name),0);keypoints,_=sift.detectAndCompute(gray,mask);detected=len(keypoints);db_is_retained=min(detected,4096)==n
  def count(group):return {'total':len(group),'inside_conservative_sky':sum(bool(issky[j]) for j in group)}
  items.append({'image':name,'db_image_id':iid,'detected_with_existing_precise_mask_8192_cap':detected,'retained_4096_cap_expected':min(detected,4096),'db_keypoints':n,'database_count_matches_detected_retained':db_is_retained,'all_keypoints_in_sky':int(issky.sum()),'unique_raw_matched':count(rawids),'unique_verified_matched':count(verifiedids),'final_model':count(fin),'final_model_reciprocal':count(reciprocal),'model_point2d_index_and_db_index_share_identity':'same COLMAP image id, same point2D ordering; index checked below','all_model_xy_matches_db':all(np.linalg.norm(im.point2D(j).xy-xy[j])<1e-4 for j in range(n)),'verified_not_raw':len(verifiedids-rawids)})
after={str(f):sha(f) for f in source};out={'source':'SIFT+LightGlue 4096-cap precise-mask 166-frame targeted-gap-v2; database.db and models/0 of same run; not 1024-cap recovery and not raw unmasked detection','detector_note':'Rerun same OpenCV detector+mask; nfeatures8192 upper target, then 4096 cap; exact original uncapped detection counts were not persisted. Database original retained keypoints and match indices are authoritative.','source_hashes_before':before,'inputs_unchanged':before==after,'frames':items,'caveat':'Unique feature indices across all pairs, not numbers of pairwise matches. Sky sample is hand-drawn partial interior, not full sky. Counts for detections within sample and mask based on retained database keypoints. Same-model reciprocal 3D not independent truth.'};(root/'provenance.json').write_text(json.dumps(out,indent=2));print(json.dumps(items,indent=2),flush=True)
