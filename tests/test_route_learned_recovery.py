import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.pilot import route_learned_recovery as recovery


def setup_source(tmp_path):
    job = tmp_path / 'job'
    prepared = job / 'prepared'
    (prepared / 'images').mkdir(parents=True)
    (prepared / 'masks').mkdir()
    (job / 'input').mkdir()
    (job / 'input/manifest.json').write_bytes(b'{}')
    rows = []
    for i in range(14):
        name = f'{i:08}.png'
        rows.append(dict(image='images/' + name,png_sha256=hashlib.sha256(b'original RGB').hexdigest()))
        (prepared / 'images' / name).write_bytes(b'original RGB')
        (prepared / 'masks' / (name + '.png')).write_bytes(b'original mask')
    (prepared / 'reconstruction-input.json').write_text(json.dumps(dict(
        source_manifest_sha256=hashlib.sha256(b'{}').hexdigest(), images=rows)))
    (prepared / 'features.json').write_bytes(b'baseline features')
    return job, prepared


def geometry(count=14):
    return dict(cameras=[dict(image=f'{i:08}.png', ticks_90k=i * 45000,
                              center=[i * .5, 0., 0.],
                              intrinsics=dict(width=1920, height=1080, fx=960, fy=960))
                         for i in range(count)])


def model(*, collapsed=False, count=14, error=1.):
    return SimpleNamespace(geometry=geometry(count), collapsed=collapsed,
                           points3D={1: SimpleNamespace(xyz=[0, 0, 2])},
                           num_points3D=lambda:500, compute_mean_reprojection_error=lambda:error)


def setup_native(monkeypatch, candidates):
    seen = dict(matcher_calls=0)

    class Token:
        def cancel(self):
            seen['cancelled'] = True

    def options(**kwargs):
        seen['options'] = kwargs
        return kwargs

    def mapping(database, images, output, **kwargs):
        seen['mapping_images'] = images
        return candidates

    monkeypatch.setitem(sys.modules, 'pycolmap', SimpleNamespace(
        CancellationToken=Token, IncrementalPipelineOptions=options, incremental_mapping=mapping))
    monkeypatch.setattr(recovery, 'available', lambda _:True)
    monkeypatch.setattr(recovery, 'recovery_device', lambda :'cpu')
    from scripts.pilot import reconstruct_route, reconstruction_quality
    monkeypatch.setattr(reconstruct_route, 'model_geometry', lambda rec, _:rec.geometry)
    monkeypatch.setattr(reconstruction_quality, 'sparse_condition',
                        lambda cameras, points:dict(passed=cameras[0][0] != -100))
    monkeypatch.setattr(reconstruction_quality, 'pinhole_condition', lambda *args:dict(passed=True))

    def matching(root, prepared, database, reader, token, check, **kwargs):
        seen['matcher_calls'] += 1
        seen['matcher_options'] = kwargs
        check()
        (prepared / 'features.json').write_bytes(b'alternative features')

    monkeypatch.setattr(recovery, 'extract_and_match', matching)
    return seen


def run(job, prepared, baseline, **kwargs):
    return recovery.recover_with_learned(job, prepared, baseline, 14, 0., 6.5,
                                         object(), kwargs.get('check', lambda:None), lambda *args:None)


def test_missing_local_matcher_never_imports_native_or_downloads(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    monkeypatch.setattr(recovery, 'available', lambda _:False)
    monkeypatch.setattr(recovery, 'extract_and_match', lambda *args, **kwargs:pytest.fail('must not load matcher'))
    baseline = object()
    chosen, report = run(job, prepared, baseline)
    assert chosen is baseline and not report['accepted']
    assert report['reason'] == 'learned_matching_unavailable'
    assert not report['network_downloads']
    assert (prepared / 'learned-recovery/result.json').is_file()


def test_changed_rgb_cannot_be_rebound_to_original_video(tmp_path,monkeypatch):
    job,prepared=setup_source(tmp_path)
    setup_native(monkeypatch,{0:model()})
    (prepared/'images/00000000.png').write_bytes(b'different RGB')
    chosen,report=run(job,prepared,None)
    assert chosen is None and not report['accepted']
    assert report['error_code']=='learned_recovery_image_changed'
    assert not (prepared/'learned-recovery/database.db').exists()


@pytest.mark.parametrize('reason', ['cancelled','resource_guard'])
def test_evaluate_propagates_diagnostic_check_failure(tmp_path,monkeypatch,reason):
    job,prepared=setup_source(tmp_path)
    candidate=model();setup_native(monkeypatch,{0:candidate})
    def check():raise RuntimeError(reason)
    with pytest.raises(RuntimeError,match=reason):
        recovery._evaluate(candidate,prepared,14,0,6.5,check=check)


def test_success_uses_isolated_identical_source_and_cpu_budget(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    candidate = model()
    seen = setup_native(monkeypatch, {0:candidate})
    chosen, report = run(job, prepared, None)
    assert chosen is candidate and report['accepted']
    assert report['baseline'] is None
    assert report['models'][0]['route_admissible']
    # This synthetic model has no reciprocal observation API: a missing
    # diagnostic is invalid, while the existing admission rule is unchanged.
    assert report['models'][0]['observation_support']['status'] == 'invalid'
    assert report['models'][0]['observation_support']['admission_effect'] == 'none'
    assert seen['matcher_options']['device'] == 'cpu'
    assert seen['matcher_options']['max_features'] == 1024
    assert seen['options']['num_threads'] == 2
    assert seen['options']['max_runtime_seconds'] == 180
    assert seen['options']['max_num_models'] == 4
    assert seen['options']['ignore_watermarks']
    assert not seen['options']['structure_less_registration_fallback']
    assert not seen['options']['ba_refine_sensor_from_rig']
    assert (prepared / 'features.json').read_bytes() == b'baseline features'
    alternative = prepared / 'learned-recovery'
    assert (alternative / 'features.json').read_bytes() == b'alternative features'
    for source in [prepared / 'reconstruction-input.json', *sorted((prepared / 'images').iterdir()),
                   *sorted((prepared / 'masks').iterdir())]:
        target = alternative / source.relative_to(prepared)
        assert source.read_bytes() == target.read_bytes()
    assert not report['physical_actions'] and not report['execution_qualified']


def test_existing_intent_cannot_start_a_second_matcher(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    seen = setup_native(monkeypatch, {})
    run(job, prepared, None)
    with pytest.raises(RuntimeError, match='learned_recovery_existing_intent'):
        run(job, prepared, None)
    assert seen['matcher_calls'] == 1


def test_collapsed_complete_model_cannot_replace_baseline_or_smaller_supported_route(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    baseline = model(count=10)
    collapsed = model(error=.001)
    collapsed.geometry['cameras'][0]['center'][0] = -100
    setup_native(monkeypatch, {0:collapsed})
    chosen, report = run(job, prepared, baseline)
    assert chosen is baseline and not report['accepted']
    assert 'camera_geometry_degenerate' in report['models'][0]['scene_reasons']
    assert (prepared / 'learned-recovery/geometry-0.json').is_file()


def test_clean_segment_missing_tail_is_retained_but_not_adopted(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    baseline = model(count=10)
    partial = model(count=10)
    setup_native(monkeypatch, {0:partial})
    chosen, report = run(job, prepared, baseline)
    assert chosen is baseline and not report['accepted']
    assert report['models'][0]['scene_admissible']
    assert not report['models'][0]['route_admissible']


@pytest.mark.parametrize('reason', ['cancelled', 'resource_guard'])
def test_cancellation_and_resource_refusals_propagate_with_durable_result(tmp_path, monkeypatch, reason):
    job, prepared = setup_source(tmp_path)
    setup_native(monkeypatch, {})
    checks = []

    def check():
        checks.append(1)
        if len(checks) >= 3:
            raise RuntimeError(reason)

    with pytest.raises(RuntimeError, match=reason):
        run(job, prepared, None, check=check)
    report = json.loads((prepared / 'learned-recovery/result.json').read_bytes())
    assert not report['accepted'] and report['reason'] == reason


def test_matcher_error_is_reported_without_adopting_or_repeating(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    setup_native(monkeypatch, {})

    def failed(*args, **kwargs):
        raise RuntimeError('learned_matching_insufficient_features')

    monkeypatch.setattr(recovery, 'extract_and_match', failed)
    chosen, report = run(job, prepared, None)
    assert chosen is None and not report['accepted']
    assert report['reason'] == 'learned_recovery_inconclusive'
    assert report['error_type'] == 'RuntimeError'
    assert report['error_code'] == 'learned_matching_insufficient_features'


def test_source_binding_change_is_rejected_before_matching(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    seen = setup_native(monkeypatch, {})
    (job / 'input/manifest.json').write_bytes(b'{"changed":true}')
    chosen, report = run(job, prepared, None)
    assert chosen is None and not report['accepted']
    assert seen['matcher_calls'] == 0


def test_valid_route_does_not_replace_equally_good_baseline(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    baseline, candidate = model(error=.5), model(error=1.)
    setup_native(monkeypatch, {0:candidate})
    chosen, report = run(job, prepared, baseline)
    assert chosen is baseline and not report['accepted']
    assert report['models'][0]['route_admissible']


def test_best_admissible_model_wins_over_larger_collapsed_one(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    good, bad = model(count=12), model()
    good.geometry['cameras'][-1]['ticks_90k'] = 585000
    good.geometry['cameras'][-1]['center'][0] = 6.5
    # Keep the observed interval at one second while retaining both endpoints.
    good.geometry['cameras'][-2]['ticks_90k'] = 495000
    good.geometry['cameras'][-2]['center'][0] = 5.5
    bad.geometry['cameras'][0]['center'][0] = -100
    setup_native(monkeypatch, {0:bad, 1:good})
    chosen, report = run(job, prepared, None)
    assert chosen is good and report['accepted'] and report['chosen_model'] == '1'


def test_source_symlink_is_never_followed(tmp_path, monkeypatch):
    job, prepared = setup_source(tmp_path)
    seen = setup_native(monkeypatch, {})
    source = prepared / 'images/00000000.png'
    source.unlink()
    try:
        source.symlink_to(prepared / 'images/00000001.png')
    except OSError:
        pytest.skip('symlink creation unavailable')
    chosen, report = run(job, prepared, None)
    assert chosen is None and not report['accepted']
    assert seen['matcher_calls'] == 0
