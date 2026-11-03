import json
import zipfile
from types import SimpleNamespace

from scripts.pilot.walk_diagnostics import WalkFrameArchive, bounded_localization_diagnostic


def test_runtime_motion_and_confirmation_fields_are_allowlisted():
    import math
    value=bounded_localization_diagnostic(dict(verifiedInliersBeforeTemporalGate=512,
        verifiedMedianErrorPx=.095,motionCenterDeltaUnits=.0002406,motionProgressDeltaUnits=.0015656,
        motionLimitUnits=.0002386,motionTurnRadians=.1,confirmationValidCount=3,
        confirmationObservationCount=5,confirmationPolicy='distinct_current_pose_3of5_source_bound_1second_v1',
        jpeg=b'secret',authorization='secret'))
    assert value['verifiedInliersBeforeTemporalGate']==512
    assert value['motionCenterDeltaUnits']==.0002406 and value['motionLimitUnits']==.0002386
    assert value['confirmationValidCount']==3 and 'jpeg'not in value and 'authorization'not in value
    bad=bounded_localization_diagnostic(dict(verifiedInliersBeforeTemporalGate=True,
        verifiedMedianErrorPx=float('nan'),motionCenterDeltaUnits=-1,motionTurnRadians=math.pi+.001,
        confirmationValidCount=6,confirmationPolicy='secret'))
    assert all(key not in bad for key in ('verifiedInliersBeforeTemporalGate','verifiedMedianErrorPx',
        'motionCenterDeltaUnits','motionTurnRadians','confirmationValidCount','confirmationPolicy'))


def test_runtime_ring_keeps_alternating_outcomes_metadata_only_and_bounds_disk(tmp_path):
    import time

    from scripts.pilot.walk_diagnostics import RuntimeMetadataRing
    ring=RuntimeMetadataRing(tmp_path)
    try:
        for i in range(100):
            ring.offer(sequence=i,pose=dict(state='confirming'if i%2 else'unknown',
                reason='route_pose_discontinuity',inliers=0,rawJPEG=b'DO_NOT_STORE'),
                diagnostic=dict(verifiedInliersBeforeTemporalGate=512,motionCenterDeltaUnits=.0002406,
                    motionLimitUnits=.0002386,authorization='DO_NOT_STORE'),
                plan=dict(phase='following',reason='vehicle_continuous_pursuit',pedal='throttle',
                    targetSpeedKmh=10,observedSpeedKmh=0,secret='DO_NOT_STORE'),compute_ms=91.)
        assert ring.offer(sequence=99,pose=dict(state='confirming',reason='route_pose_discontinuity',inliers=0),
            diagnostic=dict(verifiedInliersBeforeTemporalGate=512),
            plan=dict(phase='following',reason='vehicle_continuous_pursuit',pedal='throttle'))
        deadline=time.monotonic()+2.5
        while time.monotonic()<deadline:
            path=tmp_path/ring.FILE
            if path.is_file():
                saved=json.loads(path.read_bytes())
                if saved['rows'][-1].get('sequence')==99:break
            time.sleep(.02)
        raw=path.read_bytes();assert len(raw)<65536 and b'DO_NOT_STORE'not in raw
        rows=json.loads(raw)['rows'];assert len(rows)<=64 and rows[-1]['sequence']==99
        assert {'unknown','confirming'}<={row['poseState']for row in rows}
        assert rows[-1]['plan']['pedal']=='throttle'
        assert rows[-1]['localizationDiagnostic']['verifiedInliersBeforeTemporalGate']==512
        assert ring.writes<=2
    finally:ring.close()
    assert not ring._thread.is_alive() and not ring.offer(pose={})


def test_runtime_writer_is_singleton_and_close_releases_owned_thread(tmp_path):
    import pytest

    from scripts.pilot.walk_diagnostics import RuntimeMetadataRing
    first=RuntimeMetadataRing(tmp_path)
    try:
        with pytest.raises(ValueError,match='writer_owned'):RuntimeMetadataRing(tmp_path)
    finally:first.close()
    second=RuntimeMetadataRing(tmp_path)
    second.close();second.close()
    assert not second._thread.is_alive()


def test_runtime_offer_never_calls_disk_writer_and_contention_is_nonblocking(tmp_path,monkeypatch):
    import threading

    from scripts.pilot.walk_diagnostics import RuntimeMetadataRing
    calls=[];main=threading.get_ident();written=threading.Event()
    def write(self,rows):calls.append(threading.get_ident());written.set()
    monkeypatch.setattr(RuntimeMetadataRing,'_write_snapshot',write)
    ring=RuntimeMetadataRing(tmp_path)
    try:
        ring._lock.acquire()
        try:assert ring.offer(pose={})is False
        finally:ring._lock.release()
        assert ring.offer(pose={})is True
        assert written.wait(.5)
    finally:ring.close()
    assert all(value!=main for value in calls)


def test_runtime_disk_failure_cannot_escape_to_session(tmp_path,monkeypatch):
    import time

    from scripts.pilot.walk_diagnostics import RuntimeMetadataRing
    def denied(self,rows):raise PermissionError('fixture_denial')
    monkeypatch.setattr(RuntimeMetadataRing,'_write_snapshot',denied)
    ring=RuntimeMetadataRing(tmp_path)
    try:
        assert ring.offer(pose=dict(state='unknown',reason='route_pose_not_verified',inliers=0))
        deadline=time.monotonic()+.5
        while not ring.write_errors and time.monotonic()<deadline:time.sleep(.01)
        assert ring.write_errors==1
    finally:ring.close()


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


def test_subpixel_diagnostics_report_the_actual_gate_metric_and_drop_invalid_values():
    from scripts.pilot.walk_diagnostics import MOTION_TELEMETRY_POLICY
    value = bounded_localization_diagnostic(dict(motionSubpixelDeltaPx=.31,
        motionSubpixelCapUnits=.004, motionBaseLimitUnits=.0002, motionAllowanceUnits=.004,
        motionConsistencyPolicy=MOTION_TELEMETRY_POLICY, motionSubpixelEligible=True))
    assert value['motionSubpixelDeltaPx'] == .31 and value['motionSubpixelEligible'] is True
    assert value['motionBaseLimitUnits'] < value['motionAllowanceUnits']
    invalid = bounded_localization_diagnostic(dict(motionSubpixelDeltaPx=float('inf'),
        motionSubpixelCapUnits=-1., motionBaseLimitUnits=True, motionAllowanceUnits=1e13,
        motionConsistencyPolicy='unreviewed', motionSubpixelEligible=1))
    assert not any(key in invalid for key in ('motionSubpixelDeltaPx', 'motionSubpixelCapUnits',
        'motionBaseLimitUnits', 'motionAllowanceUnits', 'motionConsistencyPolicy', 'motionSubpixelEligible'))


def test_local_source_window_diagnostics_keep_camera_units_separate_from_hud_speed():
    from scripts.pilot.walk_diagnostics import SOURCE_MOTION_TELEMETRY_POLICY
    value = bounded_localization_diagnostic(dict(motionSourcePolicy=SOURCE_MOTION_TELEMETRY_POLICY,
        motionSourceEnvelopeEligible=True, motionSourceArcEpsilonUnits=.004568,
        motionSourceFirstSeconds=0., motionSourceLastSeconds=2.02463,
        motionSourceWindowStartSeconds=0., motionSourceWindowEndSeconds=2.52463,
        motionSourceMaxSpeedUnitsPerSecond=1.04087, motionSourceLimitUnits=.2602))
    assert value['motionSourcePolicy'] == SOURCE_MOTION_TELEMETRY_POLICY
    assert value['motionSourceLastSeconds'] < value['motionSourceWindowEndSeconds']
    assert value['motionSourceMaxSpeedUnitsPerSecond'] == 1.04087
    assert 'targetSpeedKmh' not in value
