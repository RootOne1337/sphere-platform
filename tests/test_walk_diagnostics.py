import json
from types import SimpleNamespace
import zipfile

from scripts.pilot.walk_diagnostics import WalkFrameArchive


def test_exact_queries_are_bounded_and_written_only_when_session_finishes(tmp_path):
    now=[100.];archive=WalkFrameArchive(tmp_path,'a'*32,clock=lambda:now[0])
    pose=SimpleNamespace(state='unknown',reason='route_pose_not_verified',inliers=0,center=None,rotation=None,segment=None)
    for i in range(40):
        now[0]+=.6;archive.offer(b'jpeg'+bytes([i])*200000,sequence=i,pose=pose,plan=None,method='descriptor_pnp',compute_ms=20)
    assert not (tmp_path/'walk-diagnostics').exists()
    result=archive.finish();assert result['state']=='saved' and result['frames']<=12 and result['bytes']<=2*1024**2
    with zipfile.ZipFile(tmp_path/'walk-diagnostics'/('a'*32+'.zip')) as z:
        rows=json.loads(z.read('metadata.json'))['frames']
        assert rows[-1]['sequence']==39
        assert z.read('frame-000039.jpg')==b'jpeg'+bytes([39])*200000
    assert archive.finish()==result
