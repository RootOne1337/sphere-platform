"""Provenance is inspectable evidence, not a replacement for runtime gates."""
import hashlib
import json
from pathlib import Path

from scripts.pilot.route_reconstruction_recipe import admission_ladder, bind_geometry, route_recipe


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_fixture(tmp_path):
    for name,body in (('input/manifest.json', {'source':1}),
                      ('prepared/reconstruction-input.json', {'selected':[0,10]}),
                      ('geometry.json', {'cameras':[]})):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(body),encoding='utf-8')
    recipe=route_recipe(tmp_path,tmp_path/'prepared',vehicle=True,fused_enabled=False)
    bind_geometry(recipe,tmp_path/'geometry.json')
    quality=dict(reconstruction_recipe=recipe,selection=dict(route_admissible=True),
                 registered=173,selected=173,points=20556)
    (tmp_path/'quality.json').write_text(json.dumps(quality),encoding='utf-8')
    return quality


def ladder(path,result):
    return admission_ladder(path,result,read_json=lambda p:json.loads(p.read_bytes()),digest=digest)


def test_bound_geometry_does_not_promote_rejected_runtime_map_or_execution(tmp_path):
    bind_fixture(tmp_path)
    result=dict(phase='rejected',error='route_map_has_unobserved_sections',summary=dict(
        map_support=dict(all_reference_neighborhoods_supported=False,
            all_reference_intervals_observed=True,
            unobserved_intervals=[dict(start_seconds=4.049,end_seconds=5.478)]),
        source_coverage=dict(endpoints_observed=True)))
    report=ladder(tmp_path,result)
    assert report['recipe']['status']=='recorded'
    assert report['geometry']['status']=='accepted'
    assert report['geometry']['points']==20556
    assert report['runtime_map']['status']=='not_admitted'
    assert report['runtime_map']['unobserved_intervals']==[dict(start_seconds=4.049,end_seconds=5.478)]
    assert report['route_execution']['status']=='not_validated'
    assert report['execution_qualified'] is False
    assert result['phase']=='rejected'


def test_changed_manifest_geometry_or_selected_index_cannot_inherit_geometry_admission(tmp_path):
    bind_fixture(tmp_path)
    for name in ('input/manifest.json','geometry.json','prepared/reconstruction-input.json'):
        path=tmp_path/name;before=path.read_bytes();path.write_bytes(b'{"changed":true}')
        report=ladder(tmp_path,dict(phase='not_prepared'))
        assert report['recipe']['status']=='source_changed'
        assert report['geometry']['status']=='unknown'
        assert report['runtime_map']['status']=='not_admitted'
        path.write_bytes(before)


def test_historical_geometry_remains_unknown_recipe_even_if_runtime_receipt_ready(tmp_path):
    (tmp_path/'quality.json').write_text('{"registered":173,"points":20556}')
    report=ladder(tmp_path,dict(phase='ready'))
    assert report['recipe']==dict(status='unknown',reason='historical_recipe_unrecorded')
    assert report['geometry']['status']=='unknown'
    assert report['runtime_map']['status']=='accepted'
    assert report['execution_qualified'] is False


def test_first_pass_only_never_claims_finished_geometry_and_intervals_stay_bounded(tmp_path):
    quality=bind_fixture(tmp_path);quality['first_pass_only']=True
    (tmp_path/'quality.json').write_text(json.dumps(quality))
    rows=[dict(start_seconds=i,end_seconds=i+.5) for i in range(100)]
    report=ladder(tmp_path,dict(phase='rejected',summary=dict(map_support=dict(unobserved_intervals=rows))))
    assert report['geometry']['status']=='not_admitted'
    assert len(report['runtime_map']['unobserved_intervals'])==12


def test_new_recipe_records_exact_mask_policy_plan_and_producer_hash(tmp_path):
    from scripts.pilot import route_masks

    (tmp_path/'input').mkdir()
    (tmp_path/'prepared').mkdir()
    manifest = dict(config=dict(profile=dict(mode='vehicle_buttons',
                                            hudProfile='black_russia_scooter_v1')))
    (tmp_path/'input/manifest.json').write_text(json.dumps(manifest))
    (tmp_path/'prepared/reconstruction-input.json').write_text('{}')
    (tmp_path/'control.json').write_text('{"mask":"game"}')
    before = (tmp_path/'input/manifest.json').read_bytes()
    recipe = route_recipe(tmp_path, tmp_path/'prepared', vehicle=True, fused_enabled=False)
    plan = route_masks.capture_mask_plan('game', manifest)
    assert recipe['mask_plan'] == plan
    assert recipe['mask_plan_sha256'] == plan['sha256']
    assert recipe['mask_module_sha256'] == digest(Path(route_masks.__file__))
    assert recipe['producer_sources']['route_masks.py'] == recipe['mask_module_sha256']
    assert recipe['mask_plan']['policy_id'] == route_masks.PRECISE_SCOOTER_POLICY
    assert recipe['execution_qualified'] is False
    assert (tmp_path/'input/manifest.json').read_bytes() == before
