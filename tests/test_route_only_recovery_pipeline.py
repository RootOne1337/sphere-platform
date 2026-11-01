"""Exercise the real route-only branch: recovery must not depend on dense mode."""
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.pilot import reconstruct_route as pipeline


def setup_pipeline(tmp_path,monkeypatch,*,accepted=True):
    from scripts.pilot import route_learned_recovery,route_motion_sampling,route_video_tracks,learned_route_features
    job=tmp_path/'job';job.mkdir();calls=[]
    baseline=SimpleNamespace(num_reg_images=lambda:12,num_points3D=lambda:500,
                             compute_mean_reprojection_error=lambda:1.)
    candidate=SimpleNamespace(num_reg_images=lambda:12,num_points3D=lambda:600,
                              compute_mean_reprojection_error=lambda:.8,
                              write=lambda path:calls.append('write_model'),
                              export_PLY=lambda path:calls.append('write_points'))
    capture=SimpleNamespace(manifest=dict(config=dict(profile=dict(mode='vehicle_buttons'))),
                            frames=[dict(index=i,relative_ticks_90k=i*45000) for i in range(12)])
    monkeypatch.setattr(pipeline,'checkpoint',lambda _:None)
    monkeypatch.setattr(pipeline,'validate_browser',lambda _:capture)
    monkeypatch.setattr(pipeline,'learned_features_available',lambda _:False)
    def prepare(_source,prepared,**kwargs):
        (prepared/'images').mkdir(parents=True)
        for i in range(12):(prepared/'images'/f'{i:08}.png').write_bytes(b'RGB')
    monkeypatch.setattr(pipeline,'prepare_browser',prepare)
    monkeypatch.setattr(pipeline,'masked_inputs',lambda *args,**kwargs:None)
    monkeypatch.setattr(route_motion_sampling,'sample_video',lambda *args:(frozenset(range(12)),{}))
    def tracks(*args,**kwargs):
        assert kwargs['wide_tracking'] is True
        return dict(pairs=[],decodedFrames=12,observations=1000,seconds=.1)
    monkeypatch.setattr(route_video_tracks,'build_video_track_database',tracks)
    monkeypatch.setattr(learned_route_features,'verify_pairs',lambda *args,**kwargs:None)
    def options(**kwargs):
        assert kwargs['ignore_watermarks'] is True
        return kwargs
    native=SimpleNamespace(__version__='4.2.1',CancellationToken=lambda:object(),
        ImageReaderOptions=lambda **kwargs:SimpleNamespace(**kwargs),
        Database=SimpleNamespace(open=lambda _:SimpleNamespace(close=lambda:None)),
        import_images=lambda *args,**kwargs:None,CameraMode=SimpleNamespace(SINGLE=1),
        IncrementalPipelineOptions=options,incremental_mapping=lambda *args,**kwargs:{0:baseline})
    monkeypatch.setitem(sys.modules,'pycolmap',native)
    geometry=dict(cameras=[dict(center=[i,0,0],ticks_90k=i*45000) for i in range(12)],points=[])
    def assessment(rec,*args,**kwargs):
        valid=rec is candidate
        return geometry,dict(route_admissible=valid,scene_admissible=valid,coverage=1.,registered=12,
            reprojection_px=.8 if valid else 1.,points=600 if valid else 500,
            conditioning=dict(passed=valid),intrinsics_condition=dict(passed=True))
    monkeypatch.setattr(pipeline,'model_assessment',assessment)
    monkeypatch.setattr(pipeline,'model_geometry',lambda *args:geometry)
    def recover(*args,**kwargs):
        calls.append('recovery')
        return (candidate if accepted else baseline),dict(accepted=accepted,models=[{}],reason='checked')
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',recover)
    monkeypatch.setattr(pipeline,'finish_sparse',lambda *args,**kwargs:calls.append('sealed'))
    return job,calls


def test_full_count_collapsed_route_runs_recovery_even_when_learned_dense_is_disabled(tmp_path,monkeypatch):
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    assessed=[]; original=pipeline.model_assessment
    def counted(rec,*args,**kwargs):
        assessed.append(rec)
        return original(rec,*args,**kwargs)
    monkeypatch.setattr(pipeline,'model_assessment',counted)
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert len(assessed)==2 and assessed[0] is not assessed[1]
    assert calls==['recovery','write_model','write_points','sealed']
    quality=json.loads((job/'quality.json').read_text())
    assert quality['selection']['route_admissible'] and quality['learned_recovery']['accepted']
    assert (job/'geometry-candidates.json').is_file()


def test_unsuccessful_recovery_cannot_seal_collapsed_baseline(tmp_path,monkeypatch):
    job,calls=setup_pipeline(tmp_path,monkeypatch,accepted=False)
    with pytest.raises(RuntimeError,match='camera_geometry_degenerate'):
        pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['recovery']
    assert not (job/'sparse-receipt.json').exists()


def test_refused_optional_model_load_keeps_first_pass_evidence(tmp_path,monkeypatch):
    from scripts.pilot import route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    def refused(*args,**kwargs):raise RuntimeError('resource_guard')
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',refused)
    with pytest.raises(RuntimeError,match='resource_guard'):
        pipeline.reconstruct(job,'game',30000,route_only=True)
    assert (job/'geometry.json').is_file()
    assert json.loads((job/'quality.json').read_text())['first_pass_only']
    assert not (job/'sparse-receipt.json').exists()


def test_recovery_mutating_same_model_forces_reassessment(tmp_path, monkeypatch):
    from scripts.pilot import route_learned_recovery
    job, calls = setup_pipeline(tmp_path, monkeypatch)
    assessments = []; original = pipeline.model_assessment
    def assess(rec, *args, **kwargs):
        assessments.append(bool(getattr(rec, 'mutated', False)))
        geometry, report = original(rec, *args, **kwargs)
        if getattr(rec, 'mutated', False):
            report.update(route_admissible=True, scene_admissible=True, conditioning=dict(passed=True))
        return geometry, report
    monkeypatch.setattr(pipeline, 'model_assessment', assess)
    def recover(_job, _prepared, baseline, *args, **kwargs):
        calls.append('recovery'); baseline.mutated = True
        baseline.write = lambda path: calls.append('write_model')
        baseline.export_PLY = lambda path: calls.append('write_points')
        return baseline, dict(accepted=True, models=[{}], reason='checked')
    monkeypatch.setattr(route_learned_recovery, 'recover_with_learned', recover)
    pipeline.reconstruct(job, 'game', 30000, route_only=True)
    assert assessments == [False, True]
    assert json.loads((job/'quality.json').read_text())['selection']['route_admissible']


def test_temporal_repair_mutating_same_model_forces_reassessment(tmp_path, monkeypatch):
    from scripts.pilot import route_temporal_repair
    job, calls = setup_pipeline(tmp_path, monkeypatch)
    baseline = sys.modules['pycolmap'].incremental_mapping()[0]
    baseline.write = lambda path: calls.append('write_model')
    baseline.export_PLY = lambda path: calls.append('write_points')
    monkeypatch.setattr(pipeline, 'learned_features_available', lambda _: True)
    monkeypatch.setattr(pipeline, 'extract_and_match', lambda *args, **kwargs: None)
    monkeypatch.setattr(route_temporal_repair, 'needs_repair', lambda *args, **kwargs: True)
    def repair(_job, _prepared, _database, rec, *args):
        rec.mutated = True
        return rec, dict(accepted=True)
    monkeypatch.setattr(route_temporal_repair, 'repair_temporally', repair)
    assessments=[]; original=pipeline.model_assessment
    def assess(rec,*args,**kwargs):
        assessments.append(bool(getattr(rec,'mutated',False)))
        geometry, report=original(rec,*args,**kwargs)
        if getattr(rec,'mutated',False):
            report.update(route_admissible=True,scene_admissible=True,conditioning=dict(passed=True))
        return geometry,report
    monkeypatch.setattr(pipeline,'model_assessment',assess)
    pipeline.reconstruct(job,'game',30000,route_only=False)
    assert assessments == [False,True]
    assert json.loads((job/'quality.json').read_text())['selection']['route_admissible']


def test_partial_completion_mutating_same_model_forces_reassessment(tmp_path, monkeypatch):
    from scripts.pilot import route_temporal_repair, route_motion_audit
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    baseline=sys.modules['pycolmap'].incremental_mapping()[0]
    baseline.num_reg_images=lambda:10
    baseline.points3D={0:SimpleNamespace(xyz=[0.,0.,2.])}
    baseline.images={0:SimpleNamespace(has_pose=True,cam_from_world=lambda:SimpleNamespace(inverse=lambda:SimpleNamespace(translation=[0.,0.,0.])))}
    baseline.write=lambda path:calls.append('write_model')
    baseline.export_PLY=lambda path:calls.append('write_points')
    monkeypatch.setattr(pipeline,'learned_features_available',lambda _:True)
    monkeypatch.setattr(pipeline,'extract_and_match',lambda *args,**kwargs:None)
    monkeypatch.setattr(pipeline,'sparse_condition',lambda *args:dict(passed=True))
    monkeypatch.setattr(route_motion_audit,'audit',lambda *args:dict(rapid_reversals=[],speed_outliers=[]))
    monkeypatch.setattr(route_temporal_repair,'needs_repair',lambda *args,**kwargs:False)
    def complete(_root,_prepared,_db,rec,_check):rec.mutated=True;return rec
    monkeypatch.setattr(pipeline,'complete_partial',complete)
    assessments=[];original=pipeline.model_assessment
    def assess(rec,*args,**kwargs):
        assessments.append(bool(getattr(rec,'mutated',False)))
        geometry,report=original(rec,*args,**kwargs)
        if getattr(rec,'mutated',False):report.update(route_admissible=True,scene_admissible=True,conditioning=dict(passed=True))
        return geometry,report
    monkeypatch.setattr(pipeline,'model_assessment',assess)
    pipeline.reconstruct(job,'game',30000,route_only=False)
    assert assessments==[False,True]
