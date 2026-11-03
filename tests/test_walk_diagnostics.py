import json
from types import SimpleNamespace
import zipfile

from scripts.pilot.walk_diagnostics import WalkFrameArchive, bounded_localization_diagnostic


def test_exact_queries_are_bounded_and_written_only_when_session_finishes(tmp_path):
    now=[100.];archive=WalkFrameArchive(tmp_path,'a'*32,clock=lambda:now[0])
    pose=SimpleNamespace(state='unknown',reason='route_pose_not_verified',inliers=0,center=None,rotation=None,segment=None)
    for i in range(40):
        now[0]+=.6;archive.offer(b'jpeg'+bytes([i])*200000,sequence=i,pose=pose,plan=None,method='descriptor_pnp',compute_ms=20)
    assert not (tmp_path/'walk-diagnostics').exists()
    result=archive.finish();assert result['state']=='saved' and result['frames']<=12 and result['bytes']<=2*1024**2
    with zipfile.ZipFile(tmp_path/'walk-diagnostics'/('a'*32+'.zip')) as z:
        rows=json.loads(z.read('metadata.json'))['frames']
        assert [row['sequence'] for row in rows[:2]]==[0,1]
        assert rows[-1]['sequence']==39
        assert z.read('frame-000039.jpg')==b'jpeg'+bytes([39])*200000
    assert archive.finish()==result


def test_real_jpegs_keep_first_two_and_latest_tail_with_bounded_numeric_diagnostic(tmp_path):
    import cv2 as cv
    import numpy as np
    now=[0.]
    archive=WalkFrameArchive(tmp_path,'b'*32,clock=lambda:now[0])
    pose=SimpleNamespace(state='unknown',reason='route_pose_not_verified',inliers=0,center=None,rotation=None,segment=None)
    expected={}
    diagnostic=dict(method='measured_reference_lk',candidateReferenceIndices=[0,17,42],
                    flowRetainedByCandidate=[4,38,12],verifiedCandidateCount=0,coarseSearchMs=1.25,
                    featurePreparationMs=2.,candidateMatchPnPMs=40.,sourceFamily='reference_lk',
                    rawDescriptors='MUST_NOT_BE_WRITTEN')
    for i in range(40):
        now[0]+=.6
        ok,jpeg=cv.imencode('.jpg',np.full((32,48,3),i*6,np.uint8))
        assert ok
        expected[i]=jpeg.tobytes()
        archive.offer(expected[i],sequence=i,pose=pose,plan=None,method='measured_reference_lk',compute_ms=44.,diagnostic=diagnostic)
    result=archive.finish()
    assert result['frames']==12 and result['bytes']<=2*1024**2
    with zipfile.ZipFile(tmp_path/'walk-diagnostics'/('b'*32+'.zip')) as z:
        metadata=json.loads(z.read('metadata.json'))
        rows=metadata['frames']
        assert metadata['retentionPolicy']=='first2_and_recent_tail'
        assert [row['sequence'] for row in rows]==[0,1,*range(30,40)]
        for row in rows:
            assert z.read(f"frame-{row['sequence']:06d}.jpg")==expected[row['sequence']]
            assert cv.imdecode(np.frombuffer(z.read(f"frame-{row['sequence']:06d}.jpg"),np.uint8),cv.IMREAD_COLOR).shape==(32,48,3)
            item=row['localizationDiagnostic']
            assert item['candidateCount']==3 and item['retainedLkCount']==54
            assert item['maxRetainedLkCount']==38 and item['verifiedCandidateCount']==0
            assert 'rawDescriptors' not in item


def test_numeric_diagnostic_tolerates_none_and_drops_uncapped_or_nonfinite_data():
    assert bounded_localization_diagnostic(None)['candidateCount'] is None
    value=bounded_localization_diagnostic(dict(method=['invalid'],candidateReferenceIndices=list(range(300)),
        flowRetainedByCandidate=[1,True,3],verifiedCandidateCount=999,coarseSearchMs=float('nan'),
        featurePreparationMs=float('inf'),candidateMatchPnPMs=-1.,queryFeatures=True,
        secret='MUST_NOT_BE_WRITTEN'),reason=['invalid'],source_family={})
    assert value['method']=='not_attempted' and value['sourceFamily']=='unknown'
    assert value['poseReason']=='unavailable'
    assert value['candidateCount'] is None and value['retainedLkCount'] is None
    assert value['verifiedCandidateCount'] is None
    assert 'coarseSearchMs' not in value and 'secret' not in value
    assert len(json.dumps(value,allow_nan=False))<1024
