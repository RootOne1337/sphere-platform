from types import SimpleNamespace
import json

import numpy as np
import pytest

from scripts.pilot import route_observation_support as support


class Feature:
    def __init__(self, pid, xy=(50., 50.)):
        self.point3D_id, self.xy = pid, xy

    def has_point3D(self):
        return self.point3D_id is not None


class Image:
    def __init__(self, index):
        self.name = f'{index}.png'
        self.points2D = []
        self.camera = SimpleNamespace(width=100, height=100,
            img_from_cam=lambda xyz: xyz[:, :2] / xyz[:, 2, None])

    def point2D(self, idx):
        return self.points2D[idx]

    def num_points2D(self):
        return len(self.points2D)

    def cam_from_world(self):
        return SimpleNamespace(rotation=SimpleNamespace(matrix=lambda: np.eye(3)), translation=np.zeros(3))


class Reconstruction:
    def __init__(self, n=4):
        self.images = {i: Image(i) for i in range(n)}
        self.points3D = {}

    def reg_image_ids(self):
        return list(self.images)

    def image(self, image_id):
        return self.images[image_id]

    def add(self, pid, image_ids, xyz=(50., 50., 1.), xy=(50., 50.)):
        elements = []
        for image_id in image_ids:
            im = self.images[image_id]
            elements.append(SimpleNamespace(image_id=image_id, point2D_idx=len(im.points2D)))
            im.points2D.append(Feature(pid, xy))
        self.points3D[pid] = SimpleNamespace(xyz=xyz, track=SimpleNamespace(elements=elements, length=lambda:len(elements)))


def bindings(rec):
    return [dict(image=image.name, ticks_90k=i * 100) for i, image in rec.images.items()]


def test_weak_frame_not_hidden_by_many_other_observations():
    rec = Reconstruction()
    rec.add(0, [0, 1, 2, 3])
    for pid in range(1, 101):
        rec.add(pid, [0, 1, 2])
    result = support.observation_support(rec, bindings(rec))
    assert result['status'] == 'complete'
    assert [r['reprojection_le_4px'] for r in result['cameras']] == [101, 101, 101, 1]
    assert result['summary']['count_under_6'] == 1
    assert result['admission_effect'] == 'none'
    assert result['execution_qualified'] is False


def test_distinct_views_and_one_point_per_image():
    rec = Reconstruction(3)
    rec.add(0, [0, 0, 1])  # three elements but only two registered views
    rec.add(1, [0, 0, 1, 2])  # eligible, contributes once per image
    result = support.observation_support(rec, bindings(rec))
    assert result['status'] == 'complete'
    assert [r['raw_eligible_tracks'] for r in result['cameras']] == [1, 1, 1]


@pytest.mark.parametrize('corruption', ['track_to_image', 'image_to_track', 'untracked_point'])
def test_inconsistent_reciprocity_is_invalid(corruption):
    rec = Reconstruction(3); rec.add(0, [0, 1, 2])
    if corruption == 'track_to_image': rec.images[0].points2D[0].point3D_id = 99
    if corruption == 'image_to_track': rec.images[0].points2D.append(Feature(0))
    if corruption == 'untracked_point': rec.images[0].points2D.append(Feature(99))
    result = support.observation_support(rec, bindings(rec))
    assert result['status'] == 'invalid'
    assert 'summary' not in result


def test_positive_depth_residual_observed_bounds_and_grid():
    rec = Reconstruction(3)
    rec.add(0, [0, 1, 2], xyz=(10, 10, 1), xy=(10, 10))
    rec.add(1, [0, 1, 2], xyz=(90, 90, 1), xy=(90, 90))
    rec.add(2, [0, 1, 2], xyz=(10, 10, -1), xy=(10, 10))
    rec.add(3, [0, 1, 2], xyz=(40, 40, 1), xy=(50, 50))
    rec.add(4, [0, 1, 2], xyz=(110, 50, 1), xy=(110, 50))
    row = support.observation_support(rec, bindings(rec))['cameras'][0]
    assert (row['raw_eligible_tracks'], row['positive_depth_inside'], row['reprojection_le_4px'], row['occupied_grid_4x4']) == (5, 3, 2, 2)


def test_resource_limits_and_missing_structure_fail_closed(monkeypatch):
    rec = Reconstruction(3); rec.add(0, [0, 1, 2])
    monkeypatch.setattr(support, 'MAX_OBSERVATIONS', 2)
    assert support.observation_support(rec, bindings(rec))['status'] == 'invalid'
    assert support.observation_support(SimpleNamespace(), [])['status'] == 'invalid'
    monkeypatch.setattr(support, 'MAX_IMAGES', 2)
    assert support.observation_support(rec, bindings(rec))['status'] == 'invalid'


@pytest.mark.parametrize('reason', ['cancelled', 'resource_guard'])
def test_mid_track_loop_check_propagates_resource_refusal(reason):
    rec = Reconstruction(3)
    for pid in range(1100): rec.add(pid, [0, 1, 2])
    checks = []
    def check():
        checks.append(len(checks))
        if len(checks) == 3: raise RuntimeError(reason)
    with pytest.raises(RuntimeError, match=reason):
        support.observation_support(rec, bindings(rec), check=check)
    assert len(checks) == 3


def test_mid_image_feature_loop_propagates_cancel():
    rec = Reconstruction(3); rec.add(0, [0, 1, 2])
    rec.images[0].points2D.extend(Feature(None) for _ in range(2100))
    checks = []
    def check():
        checks.append(1)
        if len(checks) == 3: raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        support.observation_support(rec, bindings(rec), check=check)
    assert len(checks) == 3


def test_compact_240_frame_report_fits_sealed_quality_without_relaxing_gate(tmp_path):
    from scripts.pilot.route_motion_audit import audit
    from scripts.pilot.sparse_scene_receipt import _quality
    rows = [dict(image=f'{i:08}.png', ticks_90k=i * 9000,
                 raw_eligible_tracks=1200, positive_depth_inside=1000,
                 reprojection_le_4px=i, occupied_grid_4x4=12) for i in range(240)]
    full = dict(status='complete', schema='sphere-observation-support-v1', cameras=rows,
                summary=dict(min=0, median=119.5, p10=23.9, count_under_6=6, count_under_15=15),
                summary_measure='reprojection_le_4px', track_observations=288000,
                execution_qualified=False, admission_effect='none')
    compact = support.compact_observation_support(full)
    assert compact['frame_count'] == 240 and len(compact['worst_frames']) == 12
    assert compact['worst_frames_truncated'] and compact['summary'] == full['summary']
    assert len(json.dumps(compact, indent=2).encode()) < 8192
    motion = audit({'cameras':[dict(image=r['image'], ticks_90k=r['ticks_90k'],
                                  center=[float(i % 2), 0., 0.]) for i,r in enumerate(rows)]})
    quality = dict(registered=240, selected=240, points=300, mean_reprojection_px=1.,
                   conditioning=dict(passed=True), intrinsics_condition=dict(passed=True),
                   selection=dict(motion=motion, observation_support=compact))
    data = json.dumps(quality, indent=2).encode()
    assert len(data) <= 65536
    (tmp_path/'quality.json').write_bytes(data)
    _quality(tmp_path)
    quality['conditioning']['passed'] = False
    (tmp_path/'quality.json').write_text(json.dumps(quality), encoding='utf8')
    with pytest.raises(ValueError, match='sparse_quality_gate_failed'):
        _quality(tmp_path)
