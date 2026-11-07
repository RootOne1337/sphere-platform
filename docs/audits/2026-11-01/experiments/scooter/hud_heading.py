import os,sys,time,pathlib,subprocess,hashlib,json
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='1');sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
root=pathlib.Path('.local-pilot/scooter-hud-heading-20261101');video=pathlib.Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/input');hud=pathlib.Path('.local-pilot/scooter-hud-20261101/ocr-receipted-step3.csv');hudreceipt=pathlib.Path(str(hud)+'.receipt.json');fwd=pathlib.Path('.local-pilot/scooter-calfvo-full-20261101/candidate.npz');rev=pathlib.Path('.local-pilot/scooter-calfvo-reverse-20261101/candidate.npz');files=[video/'manifest.json',video/'frames.jsonl',hud,hudreceipt,fwd,rev];G=1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
if len(sys.argv)==1:
 before={str(p):sha(p) for p in files};start=time.monotonic();samples=[];m=windows_memory();initial=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];reason=None;code=None
 if min(initial)<4.5*G:reason='admission_memory'
 else:
  with (root/'worker.log').open('w') as log:
   p=subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),'worker'],stdout=log,stderr=subprocess.STDOUT)
   while p.poll() is None:
    m=windows_memory();v=[m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes']];samples.append(v)
    if min(v)<4.5*G or time.monotonic()-start>30:reason='memory_guard' if min(v)<4.5*G else 'timeout';p.kill();p.wait();break
    time.sleep(.3)
   code=p.returncode
 after={str(p):sha(p) for p in files};r={'exit':code,'stop':reason,'seconds':time.monotonic()-start,'min_ram':min((x[0] for x in samples),default=None),'min_commit':min((x[1] for x in samples),default=None),'source_hashes_before':before,'source_hashes_after':after,'source_unchanged':before==after};(root/'receipt.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));sys.exit()
import csv,math,numpy as np,cv2
cv2.setNumThreads(2);meta=json.loads(hudreceipt.read_text());assert meta['output_csv_sha256']==sha(hud) and meta['source_manifest_sha256']==sha(video/'manifest.json');frames=[json.loads(x) for x in (video/'frames.jsonl').read_text().splitlines()];F=np.load(fwd);B=np.load(rev);assert np.array_equal(F['frame_indices'],np.arange(901)) and np.array_equal(B['frame_indices'],np.arange(900,-1,-1)) and np.array_equal(F['ticks_90k'],B['ticks_90k'][::-1]) and all(frames[i]['relative_ticks_90k']==int(F['ticks_90k'][i]) for i in range(901))
def so3(A):
 u,s,v=np.linalg.svd(A);d=np.eye(3);d[-1,-1]=np.linalg.det(u@v);return u@d@v
FR=np.array([so3(x) for x in F['trajectory_c2w'][:,:3,:3]]);BR=np.array([so3(x) for x in B['trajectory_c2w'][::-1,:3,:3]]);A=FR[0]@BR[0].T;BR=np.einsum('ij,njk->nik',A,BR)
# Initial camera x/z define a hypothetical horizontal plane; real gravity/body alignment unknown.
def heading(R):
 n=R[:,:,2];x=n[:,0];z=n[:,2];length=np.hypot(x,z);ok=length>=.15;angle=np.full(len(x),np.nan);angle[ok]=np.arctan2(x[ok],z[ok]);return angle,ok
fh,fok=heading(FR);bh,bok=heading(BR);common=fok&bok;delta=np.degrees(np.arctan2(np.sin(fh-bh),np.cos(fh-bh)));ticks=F['ticks_90k'];samples=list(csv.DictReader(hud.open(encoding='utf-8',newline='')));assert len(samples)==301 and int(samples[0]['frame_index'])==0 and int(samples[-1]['frame_index'])==900
for x in samples:
 i=int(x['frame_index']);assert int(x['relative_ticks_90k'])==int(ticks[i]);assert x['status'] in ('accepted','unknown')
intervals=[];segments=[];current=None
for left,right in zip(samples,samples[1:]):
 i,j=int(left['frame_index']),int(right['frame_index']);dt=(int(ticks[j])-int(ticks[i]))/90000;valid=left['status']=='accepted' and right['status']=='accepted' and dt<=.2;reason=[]
 if left['status']!='accepted' or right['status']!='accepted':reason.append('unknown_endpoint')
 if dt>.2:reason.append('gap_over_0.2s')
 orientation=bool(fok[i] and fok[j] and bok[i] and bok[j]);
 if not orientation:reason.append('horizontal_heading_degenerate')
 d=(float(left['hud_kmh'])+float(right['hud_kmh']))/2*dt/3.6 if valid else None;usable=valid and orientation
 entry={'frame_a':i,'frame_b':j,'start_seconds':float(ticks[i]/90000),'end_seconds':float(ticks[j]/90000),'seconds':float(dt),'speed_supported':valid,'heading_supported':orientation,'path_supported':usable,'hud_integrated_distance_game_units':d,'reasons':reason}
 intervals.append(entry)
 if not usable:current=None;continue
 if current is None:
  current={'segment':len(segments),'start_frame':i,'start_seconds':float(ticks[i]/90000),'end_frame':j,'end_seconds':float(ticks[j]/90000),'hud_distance_game_units':0.,'supported_seconds':0.,'forward_points':[[0.,0.]],'reverse_points':[[0.,0.]],'anchor':'independent_unknown_global_position'};segments.append(current)
 for key,h in [('forward_points',fh),('reverse_points',bh)]:
  direction=np.array([(math.sin(h[i])+math.sin(h[j]))/2,(math.cos(h[i])+math.cos(h[j]))/2]);last=np.array(current[key][-1]);current[key].append((last+d*direction).tolist())
 current['end_frame']=j;current['end_seconds']=float(ticks[j]/90000);current['hud_distance_game_units']+=d;current['supported_seconds']+=dt
speed_seconds=sum(x['seconds'] for x in intervals if x['speed_supported']);path_seconds=sum(x['seconds'] for x in intervals if x['path_supported']);duration=float((ticks[-1]-ticks[0])/90000);distance=sum(x['hud_integrated_distance_game_units'] or 0 for x in intervals if x['speed_supported']);absdelta=np.abs(delta[common]);common_samples=[int(x['frame_index']) for x in samples if x['status']=='accepted' and common[int(x['frame_index'])]]
report={'source':'zaezd888','frames':901,'hud_samples':len(samples),'hud_accepted_samples':sum(x['status']=='accepted' for x in samples),'hud_unknown_samples':sum(x['status']=='unknown' for x in samples),'total_seconds':duration,'speed_supported_seconds':speed_seconds,'speed_unsupported_seconds':duration-speed_seconds,'speed_supported_fraction':speed_seconds/duration,'path_supported_seconds':path_seconds,'path_unsupported_seconds':duration-path_seconds,'supported_hud_distance_game_units':distance,'distance_method':'trapezoidal between adjacent accepted sampled speeds only, dt<=0.2 sec; HUD km/h /3.6 is game-equivalent distance, not physical meters','independent_segments':len(segments),'segment_anchor':'each starts at arbitrary local zero; after any gap next position is unknown; never concatenate','forward_initial_yaw_deg':float(np.degrees(fh[0])),'reverse_initial_yaw_deg':float(np.degrees(bh[0])),'forward_final_yaw_deg':float(np.degrees(fh[-1])),'reverse_final_yaw_deg':float(np.degrees(bh[-1])),'heading_difference_all_frames_deg':{'count':int(common.sum()),'median_abs':float(np.median(absdelta)),'p90_abs':float(np.percentile(absdelta,90)),'max_abs':float(np.max(absdelta))},'heading_difference_on_accepted_samples_deg':{'count':len(common_samples),'median_abs':float(np.median(np.abs(delta[common_samples]))),'p90_abs':float(np.percentile(np.abs(delta[common_samples]),90))},'horizontal_degenerate_frames':int((~common).sum()),'assumptions':['vehicle moves forward','camera optical forward aligned with vehicle','initial camera xz plane is horizontal, up/gravity unknown','speed changes linearly between adjacent accepted samples within 0.2s','SO3 predictions from same model and same video are not ground truth'],'execution_qualified':False,'road_alignment_verified':False,'physical_metric_verified':False}
(root/'intervals.json').write_text(json.dumps(intervals,indent=2));(root/'segments.json').write_text(json.dumps(segments));(root/'report.json').write_text(json.dumps(report,indent=2));
# Plot model headings and accepted sampled speed against source time; do not draw fictitious joined positions.
w,h=1600,760;canvas=np.full((h,w,3),248,np.uint8);L,R=100,1560;top,bottom=65,420;st,sb=475,680;times=ticks/90000
cv2.putText(canvas,'Conditional headings: shared frame-0 axes; green bands = supported HUD intervals',(L,30),cv2.FONT_HERSHEY_SIMPLEX,.64,(30,30,30),1,cv2.LINE_AA)
def xx(t):return int(L+(R-L)*t/duration)
for it in intervals:
 if it['path_supported']:cv2.rectangle(canvas,(xx(it['start_seconds']),top),(xx(it['end_seconds']),sb),(228,247,228),-1)
for y,txt in [(top,'+180'),((top+bottom)//2,'0'),(bottom,'-180')]:cv2.line(canvas,(L,y),(R,y),(205,205,205),1);cv2.putText(canvas,txt,(48,y+5),cv2.FONT_HERSHEY_SIMPLEX,.4,(50,50,50),1)
def yhead(rad):return int(top+(math.pi-rad)/(2*math.pi)*(bottom-top))
for arr,ok,col in [(fh,fok,(190,80,25)),(bh,bok,(20,120,220))]:
 for i in range(900):
  if ok[i] and ok[i+1] and abs(arr[i+1]-arr[i])<math.pi:cv2.line(canvas,(xx(times[i]),yhead(arr[i])),(xx(times[i+1]),yhead(arr[i+1])),col,2,cv2.LINE_AA)
cv2.putText(canvas,'Forward', (108,450),cv2.FONT_HERSHEY_SIMPLEX,.5,(190,80,25),1);cv2.putText(canvas,'Reverse aligned at frame 0',(210,450),cv2.FONT_HERSHEY_SIMPLEX,.5,(20,120,220),1)
cv2.putText(canvas,'Accepted HUD speed (game km/h); gaps remain disconnected',(L,470),cv2.FONT_HERSHEY_SIMPLEX,.52,(30,30,30),1)
def yspeed(v):return int(sb-min(float(v),100)/100*(sb-st))
for row in samples:
 if row['status']=='accepted':cv2.circle(canvas,(xx(int(row['relative_ticks_90k'])/90000),yspeed(row['hud_kmh'])),2,(45,45,45),-1)
for a,b,it in zip(samples,samples[1:],intervals):
 if it['speed_supported']:cv2.line(canvas,(xx(it['start_seconds']),yspeed(a['hud_kmh'])),(xx(it['end_seconds']),yspeed(b['hud_kmh'])),(60,60,60),1)
for t in range(0,36,5):cv2.line(canvas,(xx(t),sb),(xx(t),sb+6),(0,0,0),1);cv2.putText(canvas,str(t),(xx(t)-5,sb+24),cv2.FONT_HERSHEY_SIMPLEX,.4,(30,30,30),1)
cv2.putText(canvas,'seconds | projected optical heading is a model hypothesis; HUD does not prove motion controls or meters',(L,735),cv2.FONT_HERSHEY_SIMPLEX,.46,(40,40,40),1);cv2.imwrite(str(root/'heading-support.png'),canvas)
print(json.dumps(report,indent=2))
