import os,sys,pathlib,json
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2');sys.path.insert(0,os.getcwd());sys.path.insert(0,str(pathlib.Path('.local-pilot/reconstruction-tools/pycolmap-4.2.1').resolve()))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
from scripts.pilot.resource_guard import windows_memory
import pycolmap as p
from scripts.pilot.route_observation_support import observation_support,compact_observation_support
root=pathlib.Path('.local-pilot/scooter-disk-lg-20261101-v4');old=pathlib.Path('.local-pilot/scooter-disk-lg-20261101-v3');models={'640x360':(old,pathlib.Path('.local-pilot/scooter-disk-cpu-20261101')),'1024x576':(root,root/'cpu')};out={}
for label,(feature,cpu) in models.items():
 m=windows_memory()
 if min(m['availableRamBytes'],m['commitLimitBytes']-m['committedBytes'])<4.5*2**30:raise RuntimeError('memory_guard')
 receipt=json.loads((feature/'result.json').read_text());run=json.loads((cpu/'report.json').read_text());a=json.loads((cpu/'assessment.json').read_text());g=json.loads((cpu/'geometry-0.json').read_text());rec=p.Reconstruction(cpu/'models/0');s=observation_support(rec,g['cameras']);(root/('observation-support-'+label+'.json')).write_text(json.dumps(s,indent=2));out[label]={'features':{'keypoint_observations':receipt['keypoint_observations'],'raw_matches':receipt['raw_match_observations'],'gpu_seconds':receipt['gpu_seconds'],'peak_gpu_reserved_GiB':receipt['peak_gpu_reserved_GiB'],'min_gpu_free_GiB':receipt['minimum_global_gpu_free_GiB'],'min_host_ram_GiB':receipt['minimum_host_available_RAM_GiB'],'pair_sha256':receipt['pairs_sha256']},'verification':json.loads((cpu/'verification.json').read_text()),'model':run['models'][0],'hud':a['hud'],'motion166':a['motion_whole166'],'motion163':a['motion_original163'],'direct_E':{k:v for k,v in a['direct_E_audit'].items() if k!='pairs'},'cheirality':{'observations':a['triangulated_observations'],'behind':a['behind_camera']},'observation_support':compact_observation_support(s)}
assert out['640x360']['features']['pair_sha256']==out['1024x576']['features']['pair_sha256'];(root/'comparison.json').write_text(json.dumps({'models':out,'caveat':'Same DISK/LG, masked 166 source frames, graph of 811 candidate pairs and fixed max1024; analysis resolution and GPU resource cap differ. Geometric verification and pose outputs are not independently ground truth; HUD same video posthoc fit65/test60. More support alone is not route acceptance.'},indent=2));
for k,v in out.items():print(k,'track_support',v['observation_support'].get('summary'),'hud',v['hud']['test_factor4'],'motion',len(v['motion166']['rapid_reversals']),len(v['motion166']['speed_outliers']),flush=True)
