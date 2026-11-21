import os,sys,json,pathlib,sqlite3,math,statistics
os.environ['OPENBLAS_NUM_THREADS']='1';sys.path.insert(0,os.getcwd())
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.route_motion_audit import audit
root=pathlib.Path('.local-pilot/scooter-auto-gap-20261101-v1');base=pathlib.Path('.local-pilot/scooter-targeted-gap-20261101-v2');original=pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101/geometry-0.json');names=[x['image'] for x in json.loads(original.read_text())['cameras']];A={x['image']:x for x in json.loads((base/'geometry-0.json').read_text())['cameras']};B={x['image']:x for x in json.loads((root/'geometry-0.json').read_text())['cameras']};common=[x for x in names if x in A and x in B]
report={'original_163_count':len(names),'common_original_views':len(common),'baseline':audit({'cameras':[A[x] for x in common]}),'new':audit({'cameras':[B[x] for x in common]}),'flagged_intervals':[],'note':'Same common original timestamps; heuristic changes are not verified physical errors, same video and model family.'}
for row in json.loads((root/'plan.json').read_text())['intervals']:
 a,b=row['first_index'],row['second_index'];ka,kb=f'{a:08d}.png',f'{b:08d}.png';entry={'a':a,'b':b,'added_indices':row['added_indices']}
 for kind,c in [('baseline',A),('new',B)]:
  if ka in c and kb in c:
   ordered=[x for x in names if x in c];steps=[math.dist(c[x]['center'],c[y]['center']) for x,y in zip(ordered,ordered[1:])];d=math.dist(c[ka]['center'],c[kb]['center']);entry[kind]={'step':d,'step_over_common_median':d/statistics.median(steps)}
 report['flagged_intervals'].append(entry)
(root/'common163-audit.json').write_text(json.dumps(report,indent=2));print('common',len(common),'baseline',len(report['baseline']['rapid_reversals']),len(report['baseline']['speed_outliers']),'new',len(report['new']['rapid_reversals']),len(report['new']['speed_outliers']));print('flagged',report['flagged_intervals'])
def rows(path,table):
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:return {pid:(n,col,bytes(blob or b'')) for pid,n,col,blob in c.execute('select pair_id,rows,cols,data from '+table)}
a=rows(base/'database.db','matches');b=rows(root/'database.db','matches');v=rows(base/'database.db','two_view_geometries');w=rows(root/'database.db','two_view_geometries');g={'prior_raw_pairs':len(a),'prior_raw_pairs_equal':sum(b.get(k)==x for k,x in a.items()),'prior_verified_records':len(v),'prior_verified_match_blobs_equal':sum(w.get(k)==x for k,x in v.items()),'qualifier':'pair ID and match blobs/counts compared; two-view matrices/config may change during calibration'};(root/'graph-preservation.json').write_text(json.dumps(g,indent=2));print('preservation',g)
