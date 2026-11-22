import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import route_component_merge as merge


def pose(center, rotation=None):
    rotation = np.eye(3) if rotation is None else np.asarray(rotation)
    center = np.asarray(center, dtype=float)
    inverse = SimpleNamespace(rotation=SimpleNamespace(matrix=lambda: rotation), translation=center)
    return SimpleNamespace(rotation=SimpleNamespace(matrix=lambda: rotation.T),
                           translation=-rotation.T @ center, inverse=lambda: inverse)


def model(ids, *, scale=1., translation=(0., 0., 0.), rotation=None):
    rotation = np.eye(3) if rotation is None else np.asarray(rotation)
    images = {}
    for identity in ids:
        center = scale * (rotation @ np.array([identity * .1, math.sin(identity) * .1, 0.])) + translation
        features = [SimpleNamespace(xy=np.array([i + .5, i + .5]), point3D_id=i + 1,
                                    has_point3D=lambda: True) for i in range(6)]
        images[identity] = SimpleNamespace(image_id=identity, name=f'{identity:08}.png',
            camera_id=1, points2D=features, num_points2D=lambda: 6,
            cam_from_world=lambda c=center, r=rotation: pose(c, r))
    points = {}
    for pid in range(1, 7):
        elements = [SimpleNamespace(image_id=i, point2D_idx=pid - 1) for i in ids]
        track = SimpleNamespace(elements=elements, length=lambda el=elements: len(el))
        points[pid] = SimpleNamespace(xyz=scale * (rotation @ np.array([0., 0., 10.])) + translation,
                                      track=track, error=1.)
    def write(path):
        (Path(path) / 'model.bin').write_bytes(b'copy-only')
    return SimpleNamespace(images=images, points3D=points,
        cameras={1: SimpleNamespace(model=0, width=100, height=100)},
        reg_image_ids=lambda: list(images), num_reg_images=lambda: len(images),
        num_points3D=lambda: len(points), write=write)


def source(tmp_path):
    job = tmp_path / 'job'
    prepared = job / 'prepared'
    (prepared / 'images').mkdir(parents=True)
    (job / 'input').mkdir()
    manifest = job / 'input/manifest.json'
    manifest.write_bytes(b'original manifest')
    (job / 'input/video.h264').write_bytes(b'original video')
    rows = []
    for i in range(1, 15):
        name = f'images/{i:08}.png'
        (prepared / name).write_bytes(bytes([i]))
        rows.append(dict(image=name, png_sha256=hashlib.sha256(bytes([i])).hexdigest()))
    (prepared / 'reconstruction-input.json').write_text(json.dumps(dict(
        images=rows, source_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())))
    with sqlite3.connect(prepared / 'database.db') as db:
        db.executescript('CREATE TABLE images(image_id INTEGER,name TEXT,camera_id INTEGER);'
                         'CREATE TABLE cameras(camera_id INTEGER,model INTEGER,width INTEGER,height INTEGER);'
                         'CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);')
        db.execute('INSERT INTO cameras VALUES (1,0,100,100)')
        for i in range(1, 15):
            db.execute('INSERT INTO images VALUES (?,?,1)', (i, f'{i:08}.png'))
            xy = np.array([[v + .5, v + .5] for v in range(6)], dtype='<f4')
            db.execute('INSERT INTO keypoints VALUES (?,6,2,?)', (i, xy.tobytes()))
    return job, prepared


def assessment(rec, *args):
    count = rec.num_reg_images()
    return dict(route_admissible=count == 14, scene_admissible=True, coverage=count / 14,
                registered=count, points=400, reprojection_px=1., observation_support={'status': 'complete'})


def orchestration(tmp_path, monkeypatch, *, result=None):
    job, prepared = source(tmp_path)
    first, second = model(range(1, 12)), model(range(8, 15))
    candidate = model(range(1, 15)) if result is None else result
    binary = tmp_path / 'colmap.exe'
    binary.write_bytes(b'pinned executable fixture')
    monkeypatch.setattr(merge, 'COLMAP', binary)
    monkeypatch.setattr(merge, 'COLMAP_SHA256', hashlib.sha256(binary.read_bytes()).hexdigest())
    monkeypatch.setattr(merge, '_evaluate', assessment)
    monkeypatch.setitem(sys.modules, 'pycolmap', SimpleNamespace(__version__='4.2.1', Reconstruction=lambda _: candidate))
    calls = []
    def native(a, b, output, exe, check):
        check()
        assert a.is_relative_to(prepared) and b.is_relative_to(prepared)
        assert a.name.startswith('input-') and b.name == 'initial'
        calls.append((a, b, output))
        return dict(exit_code=0)
    monkeypatch.setattr(merge, '_native', native)
    def run(check=lambda: None):
        return merge.merge_components(job, prepared, {0: first, 1: second}, first,
                                      14, 0., 13., check, lambda *args: None)
    return job, prepared, first, candidate, calls, run


def test_missing_optional_binary_preserves_baseline_without_loading_pycolmap(tmp_path, monkeypatch):
    job, prepared = source(tmp_path)
    monkeypatch.setattr(merge, 'COLMAP', tmp_path / 'absent.exe')
    monkeypatch.setitem(sys.modules, 'pycolmap', None)
    baseline = object()
    chosen, report = merge.merge_components(job, prepared, {0: baseline, 1: object()}, baseline,
                                           14, 0., 13., lambda: None, lambda *args: None)
    assert chosen is baseline and not report['accepted']
    assert report['reason'] == 'component_merge_unavailable'
    assert (job / report['workspace'] / 'result.json').is_file()
    assert report['physical_actions'] == 0 and not report['execution_qualified']


def test_unpinned_binary_is_not_run(tmp_path, monkeypatch):
    _, _, baseline, _, calls, run = orchestration(tmp_path, monkeypatch)
    monkeypatch.setattr(merge, 'COLMAP_SHA256', '0' * 64)
    chosen, report = run()
    assert chosen is baseline and report['reason'] == 'component_merge_binary_pin_mismatch'
    assert calls == []


def test_positive_rotated_scaled_components_have_measured_common_observations():
    theta = .3
    rotation = np.array([[math.cos(theta), -math.sin(theta), 0.],
                         [math.sin(theta), math.cos(theta), 0.], [0., 0., 1.]])
    report = merge.compatible(model(range(1, 9)), model(range(1, 9), scale=3., rotation=rotation, translation=(4., 1., 2.)))
    assert report['common_cameras'] == 8 and report['shared_triangulated_2d'] == 48
    assert report['scale'] == pytest.approx(3.) and report['rotation_max_deg'] < 1e-5
    assert report['center_residual_relative_max'] < 1e-10


@pytest.mark.parametrize('kind', ['different_ids', 'alias_name', 'wrong_rotation', 'negative_scale', 'no_2d_overlap'])
def test_camera_overlap_alone_does_not_establish_compatible_scene(kind):
    first, second = model(range(1, 8)), model(range(1, 8))
    if kind == 'different_ids':
        second = model(range(8, 15))
    elif kind == 'alias_name':
        second.images[1].name = 'unrelated.png'
    elif kind == 'wrong_rotation':
        second.images[2].cam_from_world = lambda: pose([.2, 0., 0.], np.diag([-1., -1., 1.]))
    elif kind == 'negative_scale':
        second = model(range(1, 8), scale=-1.)
    else:
        for image in second.images.values():
            for point in image.points2D:
                point.has_point3D = lambda: False
    with pytest.raises(ValueError, match='component_merge_'):
        merge.compatible(first, second)


@pytest.mark.parametrize('kind', ['duplicate', 'wrong_reciprocal', 'negative_depth', 'nan_point', 'untracked_2d'])
def test_structural_audit_rejects_invalid_scene_despite_high_camera_count(kind):
    rec = model(range(1, 15))
    if kind == 'duplicate':
        rec.points3D[1].track.elements.append(SimpleNamespace(image_id=1, point2D_idx=1))
    elif kind == 'wrong_reciprocal':
        rec.images[1].points2D[0].point3D_id = 2
    elif kind == 'negative_depth':
        rec.points3D[1].xyz[2] = -1
    elif kind == 'nan_point':
        rec.points3D[1].xyz[0] = np.nan
    else:
        rec.images[1].points2D[0].point3D_id = 123456
    with pytest.raises(ValueError, match='component_merge_'):
        merge.structural_audit(rec)


def test_namespace_checks_every_ordered_keypoint_against_readonly_database(tmp_path):
    _, prepared = source(tmp_path)
    rec = model(range(1, 8))
    names = {f'images/{i:08}.png' for i in range(1, 15)}
    before = (prepared / 'database.db').read_bytes()
    merge._namespace(rec, prepared / 'database.db', names, lambda: None)
    rec.images[3].points2D[0].xy += .5  # An extra half-pixel shift is a different namespace.
    with pytest.raises(ValueError, match='keypoint_namespace'):
        merge._namespace(rec, prepared / 'database.db', names, lambda: None)
    assert (prepared / 'database.db').read_bytes() == before


def test_valid_union_improves_assessed_baseline_without_source_or_authority_changes(tmp_path, monkeypatch):
    job, prepared, baseline, candidate, calls, run = orchestration(tmp_path, monkeypatch)
    protected = {p: p.read_bytes() for p in job.rglob('*') if p.is_file()}
    chosen, report = run()
    assert chosen is candidate and chosen is not baseline and report['accepted']
    assert report['attempts'][0]['structural']['observations'] == 84 and len(calls) == 1
    assert report['source_before'] == report['source_after'] and not report['source_modified']
    assert not report['navigation_qualified'] and not report['execution_qualified']
    assert all(p.read_bytes() == original for p, original in protected.items())
    assert not (job / 'geometry.json').exists() and not (prepared / 'models').exists()


def test_cli_exit_zero_without_union_is_not_a_success(tmp_path, monkeypatch):
    _, _, baseline, _, _, run = orchestration(tmp_path, monkeypatch, result=model(range(1, 12)))
    chosen, report = run()
    assert chosen is baseline and not report['accepted']
    assert report['attempts'][0]['reason'] == 'component_merge_camera_union_incomplete'


def test_more_cameras_do_not_override_failed_scene_assessment(tmp_path, monkeypatch):
    _, _, baseline, _, _, run = orchestration(tmp_path, monkeypatch)
    def bad(rec, *args):
        return dict(assessment(rec), scene_admissible=rec is baseline, route_admissible=False)
    monkeypatch.setattr(merge, '_evaluate', bad)
    chosen, report = run()
    assert chosen is baseline and not report['accepted']
    assert report['attempts'][0]['assessment']['registered'] == 14


@pytest.mark.parametrize('failure', ['component_merge_native_timeout', 'component_merge_native_failed'])
def test_native_failure_preserves_baseline_and_seals_refusal(tmp_path, monkeypatch, failure):
    job, _, baseline, _, _, run = orchestration(tmp_path, monkeypatch)
    def fail(*args):
        raise RuntimeError(failure)
    monkeypatch.setattr(merge, '_native', fail)
    chosen, report = run()
    assert chosen is baseline and not report['accepted']
    assert report['attempts'][0]['reason'] == failure
    assert (job / report['workspace'] / 'result.json').is_file()


def test_caller_resource_refusal_cannot_be_swallowed_by_optional_stage(tmp_path, monkeypatch):
    job, prepared, _, _, _, run = orchestration(tmp_path, monkeypatch)
    refusing = False
    def check():
        if refusing:
            raise MemoryError('resource_guard_low_ram')
    def fail(*args):
        nonlocal refusing
        refusing = True
        args[-1]()
    monkeypatch.setattr(merge, '_native', fail)
    with pytest.raises(MemoryError, match='resource_guard_low_ram'):
        run(check)
    report = json.loads(next(prepared.glob('component-merge-*/result.json')).read_bytes())
    assert not report['accepted'] and report['source_verification'] == 'incomplete'
    assert not (job / 'CANCEL').exists()


def test_cancel_arriving_with_candidate_never_adopts_and_never_removes_cancel(tmp_path, monkeypatch):
    job, prepared, _, _, _, run = orchestration(tmp_path, monkeypatch)
    original = merge._evaluate
    def evaluate(rec, *args):
        result = original(rec, *args)
        if rec.num_reg_images() == 14:
            (job / 'CANCEL').write_text('caller cancelled')
        return result
    monkeypatch.setattr(merge, '_evaluate', evaluate)
    with pytest.raises(RuntimeError, match='cancelled'):
        run()
    assert (job / 'CANCEL').read_text() == 'caller cancelled'
    report = json.loads(next(prepared.glob('component-merge-*/result.json')).read_bytes())
    assert not report['accepted'] and report['chosen'] is None


def test_source_changed_during_native_stage_defeats_candidate_adoption(tmp_path, monkeypatch):
    job, _, baseline, _, _, run = orchestration(tmp_path, monkeypatch)
    native = merge._native
    def external_change(*args):
        result = native(*args)
        (job / 'input/video.h264').write_bytes(b'concurrent source change')
        return result
    monkeypatch.setattr(merge, '_native', external_change)
    chosen, report = run()
    assert chosen is baseline and report['source_modified'] and not report['accepted']


def test_changed_prepared_image_refuses_before_any_native_work(tmp_path, monkeypatch):
    _, prepared, baseline, _, calls, run = orchestration(tmp_path, monkeypatch)
    (prepared / 'images/00000001.png').write_bytes(b'different capture')
    chosen, report = run()
    assert chosen is baseline and report['reason'] == 'component_merge_image_changed' and not calls


def test_expired_total_budget_cannot_adopt_or_start_native(tmp_path, monkeypatch):
    _, _, baseline, _, calls, run = orchestration(tmp_path, monkeypatch)
    monkeypatch.setattr(merge, 'TOTAL_SECONDS', 0)
    chosen, report = run()
    assert chosen is baseline and not report['accepted'] and not calls
    assert report['reason'] == 'component_merge_timeout'


def test_more_than_four_models_is_optional_refusal_not_an_unbounded_merge(tmp_path, monkeypatch):
    job, prepared, baseline, _, calls, _ = orchestration(tmp_path, monkeypatch)
    chosen, report = merge.merge_components(job, prepared, {i: baseline for i in range(5)}, baseline,
                                           14, 0., 13., lambda: None, lambda *args: None)
    assert chosen is baseline and not calls and report['reason'] == 'component_merge_component_count'


def test_four_components_grow_only_three_owned_native_unions(tmp_path, monkeypatch):
    job, prepared, _, _, _, _ = orchestration(tmp_path, monkeypatch)
    baseline = model(range(1, 9))
    donors = [model([5, 6, 7, 8, last]) for last in (9, 10, 11)]
    candidates = iter([model(range(1, last + 1)) for last in (9, 10, 11)])
    sys.modules['pycolmap'].Reconstruction = lambda _: next(candidates)
    calls = []
    def native(a, b, output, exe, check):
        check()
        calls.append((a, b, output))
        return dict(exit_code=0)
    monkeypatch.setattr(merge, '_native', native)
    chosen, report = merge.merge_components(job, prepared, {0: baseline, **dict(enumerate(donors, start=1))},
        baseline, 14, 0., 13., lambda: None, lambda *args: None)
    assert len(calls) == 3 and len(report['attempts']) == 3
    assert chosen.num_reg_images() == 11 and report['accepted']
    assert len({output for _, _, output in calls}) == 3
    assert all(path.is_relative_to(job / report['workspace']) for paths in calls for path in paths)


def test_combined_point_quota_is_checked_before_serializing_any_model(tmp_path, monkeypatch):
    _, _, baseline, _, calls, run = orchestration(tmp_path, monkeypatch)
    baseline.num_points3D = lambda: merge.MAX_POINTS
    chosen, report = run()
    assert chosen is baseline and not calls and report['reason'] == 'component_merge_combined_point_quota'


def test_observation_assessment_callback_refusal_propagates(tmp_path, monkeypatch):
    job, prepared, baseline, _, _, _ = orchestration(tmp_path, monkeypatch)
    donor = model(range(8, 15))
    # Exercise the real assessment forwarding path, rather than a callback-free mock.
    from scripts.pilot import reconstruct_route
    def assess(rec, prepared, selected, start, end, *, check):
        check()
        return {}, assessment(rec)
    monkeypatch.setattr(reconstruct_route, 'model_assessment', assess)
    monkeypatch.setattr(merge, '_evaluate', lambda rec, prepared, selected, start, end, check:
                        assess(rec, prepared, selected, start, end, check=check)[1])
    def refuse():
        raise ValueError('resource_guard_observations')
    with pytest.raises(ValueError, match='resource_guard_observations'):
        merge.merge_components(job, prepared, {0: baseline, 1: donor}, baseline, 14, 0., 13.,
                               lambda: None, lambda *args: None, assessment_check=refuse)
    report = json.loads(next(prepared.glob('component-merge-*/result.json')).read_bytes())
    assert not report['accepted']


def test_native_cancellation_reaps_only_owned_child(tmp_path, monkeypatch):
    """A real sleeper subprocess proves the finally path reaps the owned PID."""
    native_popen = subprocess.Popen
    spawned = []
    def spawn(*args, **kwargs):
        child = native_popen([getattr(sys, '_base_executable', sys.executable), '-c',
                              'import time; time.sleep(60)'], **kwargs)
        spawned.append(child)
        return child
    monkeypatch.setattr(merge.subprocess, 'Popen', spawn)
    def cancelled():
        raise RuntimeError('cancelled')
    output = tmp_path / 'result'
    output.mkdir()
    with pytest.raises(RuntimeError, match='cancelled'):
        merge._native(tmp_path, tmp_path, output, Path('not-executed'), cancelled)
    assert len(spawned) == 1 and spawned[0].poll() is not None


def test_native_fixture_merges_real_reprojections_with_pinned_installed_cli(tmp_path):
    """Optional small real COLMAP fixture; no model download or actual clip solve."""
    if not merge.COLMAP.is_file():
        pytest.skip('optional pinned COLMAP executable unavailable')
    p = pytest.importorskip('pycolmap')
    if p.__version__ != '4.2.1' or hashlib.sha256(merge.COLMAP.read_bytes()).hexdigest() != merge.COLMAP_SHA256:
        pytest.skip('optional pinned native versions unavailable')
    xyz = np.array([[x, y, 8. + z] for x in (-1., 0., 1.) for y in (-.5, .5) for z in (0., 1.)])
    def real(ids, scale, offset):
        rec = p.Reconstruction()
        camera = p.Camera(model='SIMPLE_PINHOLE', width=100, height=100, params=[60., 50., 50.], camera_id=1)
        rec.add_camera_with_trivial_rig(camera)
        for i in ids:
            center = np.array([i * .2, math.sin(i) * .1, math.cos(i * .7) * .1])
            xy = camera.img_from_cam(xyz - center)
            image = p.Image(name=f'{i:08}.png', keypoints=xy, camera_id=1, image_id=i)
            rec.add_image_with_trivial_frame(image, p.Rigid3d(p.Rotation3d(), -(scale * center + offset)))
        for index, point in enumerate(xyz):
            track = p.Track([p.TrackElement(i, index) for i in ids])
            rec.add_point3D(scale * point + offset, track)
        rec.update_point_3d_errors()
        return rec
    first, second = real(range(1, 9), 2., np.array([1., 2., 3.])), real(range(4, 12), 1., np.zeros(3))
    proof = merge.compatible(first, second)
    assert proof['common_cameras'] == 5 and proof['scale'] == pytest.approx(.5)
    a, b, output = (tmp_path / name for name in ('a', 'b', 'merged'))
    for path in (a, b, output):
        path.mkdir()
    first.write(a)
    second.write(b)
    immutable = {path: path.read_bytes() for directory in (a, b) for path in directory.iterdir()}
    result = merge._native(a, b, output, merge.COLMAP, lambda: None)
    candidate = p.Reconstruction(output)
    assert result['exit_code'] == 0 and set(candidate.reg_image_ids()) == set(range(1, 12))
    assert merge.structural_audit(candidate)['observations'] == len(xyz) * 11
    assert candidate.compute_mean_reprojection_error() < 1e-8
    assert all(path.read_bytes() == data for path, data in immutable.items())
