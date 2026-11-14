import json,pathlib,math,statistics
from scripts.pilot.route_motion_audit import audit
root=pathlib.Path('.local-pilot/scooter-stage-global-focal-20261101');baseline=pathlib.Path('.local-pilot/scooter-intrinsics-20261101/960/geometry-0.json');hud=json.loads(pathlib.Path('.local-pilot/scooter-fusion-20261101/speed-consistency-step3.json').read_text())['edges'];base=json.loads(baseline.read_text());bc={c['image']:c for c in base['cameras']}
def vals(cams):
 out={}
 for e in hud:
  a=cams.get(e['first_image']);b=cams.get(e['second_image']);d=e['hud_distance']
  if a and b and d and d>0:
   v=math.dist(a['center'],b['center'])/d
   if v>0:out[e['edge_index']]=v
 return out
def summary(v,ids):
 a=[v[i] for i in ids];a.sort();train=[v[i] for i in ids if i<81];test=[v[i] for i in ids if i>=81];fit=statistics.median(train) if train else None
 def p(q):
  z=(len(a)-1)*q;i=int(z);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(z-i)
 return {'count':len(ids),'p90_p10':p(.9)/p(.1) if len(a)>1 else None,'train':len(train),'test':len(test),'train_median_scale':fit,'test_median_abs_log':statistics.median(abs(math.log(x/fit)) for x in test) if fit and test else None,'test_factor4':sum(x/fit>4 or x/fit<.25 for x in test) if fit else None}
raw=vals(bc);out=[]
for f in sorted(root.glob('geometry-*.json')):
 g=json.loads(f.read_text());cams={c['image']:c for c in g['cameras']};v=vals(cams);common=sorted(set(raw)&set(v));overlap=set(cams)&set(bc);x={'geometry':f.name,'eligible_common_edges':common,'baseline':summary(raw,common),'new':summary(v,common),'common_views':len(overlap)}
 if len(overlap)>=2:
  original={'cameras':[c for c in base['cameras'] if c['image'] in overlap]};other={'cameras':[cams[c['image']] for c in original['cameras']]};x['baseline_same_views_audit']=audit(original);x['new_same_views_audit']=audit(other)
 out.append(x)
(root/'comparison.json').write_text(json.dumps({'models':out,'caveats':'Same video; pose selection and focal optimization used all frames, HUD speed and coupling unverified; heldout relates only to scale fit. Common subset can differ across components; no reconstruction autoacceptance.'},indent=2));print(json.dumps([{'geometry':x['geometry'],'common_views':x['common_views'],'baseline':x['baseline'],'new':x['new']} for x in out],indent=2))
