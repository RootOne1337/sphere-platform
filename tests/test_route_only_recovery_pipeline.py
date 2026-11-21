"""Exercise the real route-only branch: recovery must not depend on dense mode."""
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.pilot import reconstruct_route as pipeline


def setup_pipeline(tmp_path,monkeypatch,*,accepted=True):
    from scripts.pilot import route_fused_recovery,route_learned_recovery,route_motion_sampling,route_video_tracks,learned_route_features
    monkeypatch.setenv('SPHERE_EXPERIMENTAL_FUSED_RECOVERY','1')
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
    monkeypatch.setattr(route_fused_recovery,'recover_fused',lambda _job,_prepared,rec,*args,**kwargs:(rec,dict(accepted=False,reason='fixture_no_candidate')))
    monkeypatch.setattr(pipeline,'finish_sparse',lambda *args,**kwargs:calls.append('sealed'))
    return job,calls


def test_unqualified_fused_candidate_is_default_disabled_without_new_ui_switch(tmp_path,monkeypatch):
    from scripts.pilot import route_fused_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    monkeypatch.delenv('SPHERE_EXPERIMENTAL_FUSED_RECOVERY')
    monkeypatch.setattr(route_fused_recovery,'recover_fused',lambda *a,**k:pytest.fail('unqualified candidate must stay default off'))
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['recovery','write_model','write_points','sealed']
    status=json.loads((job/'quality.json').read_bytes())['fused_recovery']
    assert status['enabled'] is False and status['attempted'] is False and status['accepted'] is False


def test_native_success_records_the_actual_recipe_and_skipped_fused_decision(tmp_path,monkeypatch):
    from scripts.pilot import route_fused_recovery,route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    native=sys.modules['pycolmap'].incremental_mapping()[0]
    native.write=lambda _:calls.append('write_model')
    native.export_PLY=lambda _:calls.append('write_points')
    original=pipeline.model_assessment
    def admitted(rec,*args,**kwargs):
        geometry,report=original(rec,*args,**kwargs)
        report.update(route_admissible=True,scene_admissible=True,conditioning=dict(passed=True))
        return geometry,report
    monkeypatch.setattr(pipeline,'model_assessment',admitted)
    monkeypatch.setattr(route_fused_recovery,'recover_fused',lambda *a,**k:pytest.fail('native admission must not silently start a new recipe'))
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',lambda *a,**k:pytest.fail('no heavy fallback for native success'))
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['write_model','write_points','sealed']
    quality=json.loads((job/'quality.json').read_bytes())
    recipe=quality['reconstruction_recipe']
    assert recipe['recipe_id']=='video-fb-lk-incremental-colmap-v1'
    assert recipe['features']['method']=='source_video_corner_tracks'
    assert recipe['mapping']['method']=='incremental_mapping'
    assert all(quality['fused_recovery'][key]==value for key,value in recipe['fused_recovery'].items())
    assert recipe['fused_recovery']['enabled'] is True
    assert recipe['fused_recovery']['attempted'] is False
    assert recipe['fused_recovery']['reason']=='not_attempted_native_geometry_admitted'
    assert recipe['source']['geometry_sha256']==__import__('hashlib').sha256((job/'geometry.json').read_bytes()).hexdigest()


def test_automatic_fused_candidate_precedes_heavy_fallback_and_uses_same_admission(tmp_path,monkeypatch):
    from scripts.pilot import route_fused_recovery,route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    baseline=sys.modules['pycolmap'].incremental_mapping()[0]
    recovered=SimpleNamespace(num_reg_images=lambda:12,num_points3D=lambda:700,
        compute_mean_reprojection_error=lambda:.7,
        write=lambda _:calls.append('write_model'),export_PLY=lambda _:calls.append('write_points'))
    original=pipeline.model_assessment
    def assess(rec,*args,**kwargs):
        geometry,report=original(rec,*args,**kwargs)
        if rec is recovered:
            report.update(route_admissible=True,scene_admissible=True,conditioning=dict(passed=True))
        return geometry,report
    monkeypatch.setattr(pipeline,'model_assessment',assess)
    def recover(_job,_prepared,rec,*args,**kwargs):
        assert rec is baseline
        calls.append('fused_recovery')
        return recovered,dict(accepted=True,schema='sphere-fused-route-recovery-v1',source_modified=False)
    monkeypatch.setattr(route_fused_recovery,'recover_fused',recover)
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',lambda *a,**k:pytest.fail('admitted fused candidate must not launch heavy fallback'))
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['fused_recovery','write_model','write_points','sealed']
    quality=json.loads((job/'quality.json').read_bytes())
    assert quality['fused_recovery']['accepted'] and quality['components']==1


def test_fused_resource_failure_preserves_baseline_without_loading_heavy_fallback(tmp_path,monkeypatch):
    from scripts.pilot import route_fused_recovery,route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    def refused(*args,**kwargs):raise RuntimeError('resource_guard')
    monkeypatch.setattr(route_fused_recovery,'recover_fused',refused)
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',lambda *a,**k:pytest.fail('resource refusal must propagate'))
    with pytest.raises(RuntimeError,match='resource_guard'):
        pipeline.reconstruct(job,'game',30000,route_only=True)
    assert not calls and (job/'geometry.json').is_file()
    quality=json.loads((job/'quality.json').read_bytes())
    assert quality['first_pass_only']
    assert quality['fused_recovery']['attempted'] is True
    assert quality['fused_recovery']['accepted'] is False
    assert quality['fused_recovery']['reason']=='fused_candidate_interrupted'


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


def test_declared_vehicle_hud_is_prepared_before_visual_mapping(tmp_path,monkeypatch):
    from scripts.pilot import image_route_workspace, route_hud_profile, route_hud_workspace
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    capture=pipeline.validate_browser(job/'input')
    capture.manifest['config'].update(hud_hidden_declared=False)
    capture.manifest['config']['profile']['hudProfile']='black_russia_scooter_v1'
    capture.geometry=(1920,1080)
    monkeypatch.setattr(pipeline,'make_observation_checkpoint',lambda *a,**k:lambda:None)
    def prepare(_job,*,checkpoint):
        assert not (_job/'prepared').exists()
        checkpoint()
        calls.append('speed_reference')
    monkeypatch.setattr(route_hud_profile,'prepare_speed_reference',prepare)
    monkeypatch.setattr(route_hud_workspace,'start',lambda *a,**k:pytest.fail('fast preset must not spawn slow OCR'))
    def index(*a,**k):
        assert calls==['speed_reference']
        calls.append('image_index')
    monkeypatch.setattr(image_route_workspace,'run_optional',index)
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['speed_reference','image_index','recovery','write_model','write_points','sealed']


def test_compatible_components_are_reassessed_and_sealed_before_loading_learned_fallback(tmp_path,monkeypatch):
    from scripts.pilot import route_component_merge, route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    baseline=sys.modules['pycolmap'].incremental_mapping()[0]
    monkeypatch.setattr(sys.modules['pycolmap'],'incremental_mapping',lambda *a,**k:{0:baseline,1:baseline})
    merged=SimpleNamespace(num_reg_images=lambda:12,num_points3D=lambda:650,
        compute_mean_reprojection_error=lambda:.9,
        write=lambda _:calls.append('write_model'),export_PLY=lambda _:calls.append('write_points'))
    original=pipeline.model_assessment
    assessed=[]
    def assessment(model,*a,**k):
        assessed.append(model)
        if model is merged:
            geometry,report=original(baseline,*a,**k)
            return geometry,{**report,'route_admissible':True,'scene_admissible':True,'conditioning':dict(passed=True)}
        return original(model,*a,**k)
    monkeypatch.setattr(pipeline,'model_assessment',assessment)
    def merge(*a,**k):
        calls.append('component_merge')
        return merged,dict(schema='sphere-route-component-merge-v1',accepted=True,attempts=[{}],source_modified=False)
    monkeypatch.setattr(route_component_merge,'merge_components',merge)
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',lambda *a,**k:pytest.fail('accepted observed union must not start learned fallback'))
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['component_merge','write_model','write_points','sealed']
    assert merged in assessed
    quality=json.loads((job/'quality.json').read_text())
    assert quality['component_merge']['accepted'] and quality['components']==1 and quality['source_components']==2


def test_unsuccessful_recovery_cannot_seal_collapsed_baseline(tmp_path,monkeypatch):
    job,calls=setup_pipeline(tmp_path,monkeypatch,accepted=False)
    with pytest.raises(RuntimeError,match='camera_geometry_degenerate'):
        pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['recovery']
    assert not (job/'sparse-receipt.json').exists()


def test_endpoint_resection_reassesses_partial_route_after_database_stages(tmp_path,monkeypatch):
    from scripts.pilot import route_endpoint_resection, route_learned_recovery
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    baseline=sys.modules['pycolmap'].incremental_mapping()[0]
    baseline.num_reg_images=lambda:10
    completed=SimpleNamespace(num_reg_images=lambda:12,num_points3D=lambda:650,
        compute_mean_reprojection_error=lambda:.9,
        write=lambda _:calls.append('write_model'),export_PLY=lambda _:calls.append('write_points'))
    original=pipeline.model_assessment
    assessed=[]
    def assessment(model,*a,**k):
        assessed.append(model)
        geometry,report=original(baseline,*a,**k)
        return geometry,{**report,'route_admissible':True,'scene_admissible':True,
            'conditioning':dict(passed=True),'registered':model.num_reg_images()}
    monkeypatch.setattr(pipeline,'model_assessment',assessment)
    monkeypatch.setattr(route_learned_recovery,'recover_with_learned',lambda *a,**k:pytest.fail('admissible partial route needs no learned fallback'))
    def endpoints(*a,**k):
        assert a[2] is baseline and a[3]==12
        calls.append('endpoint_resection')
        return completed,dict(schema='sphere-endpoint-resection-v1',accepted=True,
            namespace='ENDPOINT_LK',further_original_db_matching=False,
            poses_interpolated=False,execution_qualified=False,frames=[dict(accepted=True)]*2)
    monkeypatch.setattr(route_endpoint_resection,'repair_endpoints',endpoints)
    pipeline.reconstruct(job,'game',30000,route_only=True)
    assert calls==['endpoint_resection','write_model','write_points','sealed']
    assert assessed[-1] is completed
    quality=json.loads((job/'quality.json').read_text())
    assert quality['registered']==12 and quality['endpoint_resection']['added_views']==2
    assert quality['endpoint_resection']['further_original_db_matching'] is False


def test_endpoint_resource_failure_never_seals_a_route(tmp_path,monkeypatch):
    from scripts.pilot import route_endpoint_resection
    job,calls=setup_pipeline(tmp_path,monkeypatch)
    baseline=sys.modules['pycolmap'].incremental_mapping()[0]
    baseline.num_reg_images=lambda:10
    original=pipeline.model_assessment
    def assessment(*a,**k):
        geometry,report=original(*a,**k)
        return geometry,{**report,'route_admissible':True,'scene_admissible':True}
    monkeypatch.setattr(pipeline,'model_assessment',assessment)
    def refused(*a,**k):raise RuntimeError('resource_guard')
    monkeypatch.setattr(route_endpoint_resection,'repair_endpoints',refused)
    with pytest.raises(RuntimeError,match='resource_guard'):
        pipeline.reconstruct(job,'game',30000,route_only=True)
    assert not calls and not (job/'sparse-receipt.json').exists()


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
