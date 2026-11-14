from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import route_measured_landmarks as builder
from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv


def fixture(points=((0., 0., 10.),), centers=(-.5, 0., .5)):
    raw_K = np.array([[800., 0., 960.], [0., 800., 540.], [0., 0., 1.]])
    K = colmap_calibration_to_opencv(raw_K, (1920, 1080), (960, 540))
    camera = SimpleNamespace(model_name='SIMPLE_PINHOLE', width=1920, height=1080,
                             calibration_matrix=lambda: raw_K.copy())
    images, observations, matrices = [], [], []
    for view, center in enumerate(centers):
        matrix = np.column_stack((np.eye(3), [-center, 0., 0.]))
        pose = SimpleNamespace(matrix=lambda m=matrix: m.copy())
        xy = []
        for point in points:
            q = matrix[:, :3] @ point + matrix[:, 3]
            pix = K @ q
            xy.append(pix[:2] / pix[2])
        pixels = np.asarray(xy, np.float64).reshape(-1, 2)
        source_points = [SimpleNamespace(xy=(row+.5)*2, point3D_id=100+i,
                            has_point3D=lambda: True) for i, row in enumerate(pixels)]
        images.append(SimpleNamespace(image_id=view+1, name=f'{view}.png', camera_id=1,
                       cam_from_world=lambda p=pose: p, points2D=source_points))
        descriptors = np.zeros((len(pixels), 128), np.float32)
        descriptors[:, 0] = 1
        observations.append((pixels, descriptors))
        matrices.append(matrix)
    cloud = {100+i: SimpleNamespace(xyz=np.asarray(xyz, np.float64), track=SimpleNamespace(elements=[
        SimpleNamespace(image_id=view+1, point2D_idx=i) for view in range(len(centers))]))
        for i, xyz in enumerate(points)}
    rec = SimpleNamespace(cameras={1: camera}, images={im.image_id: im for im in images}, points3D=cloud,
                          reg_image_ids=lambda: list(range(1, len(images)+1)))
    return rec, images, observations, matrices, K


def run(data, checkpoint=lambda: None):
    return builder.build(*data, checkpoint=checkpoint)


def test_reuses_measured_xyz_and_actual_medoid_without_mutating_inputs():
    data = fixture()
    for view, angle in enumerate([0., .1, .2]):
        data[2][view][1][0, :2] = [np.cos(angle), np.sin(angle)]
    before = [(p.tobytes(), d.tobytes()) for p, d in data[2]]
    valid, report = run(data)
    assert len(valid) == 1
    assert valid[0][0] == 3 and valid[0][1] == (0., 0., 10.) and valid[0][3] == (0, 1, 2)
    np.testing.assert_array_equal(valid[0][2], data[2][1][1][0])
    assert report['landmark_provenance'][0]['medoid_observation']['view'] == 1
    assert report['native_xyz_reused'] and not report['triangulation_performed']
    assert not report['poses_modified'] and not report['execution_qualified']
    assert before == [(p.tobytes(), d.tobytes()) for p, d in data[2]]


def test_colmap_pixel_corners_resize_before_half_pixel_origin_change():
    data = fixture()
    valid, report = run(data)
    assert len(valid) == 1
    source = data[0].images[1].points2D[0].xy
    expected = source * .5 - .5
    observed = report['landmark_provenance'][0]['observations'][0]
    np.testing.assert_array_equal(observed['native_runtime_xy'], expected)
    assert observed['association_px'] == 0
    assert observed['native_runtime_xy'] != list((source-.5)*.5)


def test_rejects_wrong_principal_point_convention():
    data = fixture()
    data[4][0, 2] += .25
    with pytest.raises(ValueError, match='camera_pixel_convention'):
        run(data)


@pytest.mark.parametrize('offset,accepted', [(.999, 1), (1.001, 0)])
def test_association_radius_is_bounded(offset, accepted):
    data = fixture()
    for xy, _ in data[2]:
        xy[:, 0] += offset
    valid, _ = run(data)
    assert len(valid) == accepted


def test_exact_runtime_spatial_aliases_are_ambiguous_not_greedily_chosen():
    data = fixture()
    for view, (xy, desc) in enumerate(data[2]):
        data[2][view] = (np.repeat(xy, 2, axis=0), np.repeat(desc, 2, axis=0))
    valid, report = run(data)
    assert valid == [] and report['spatial_associations'] == 0
    assert report['no_runtime_association_count'] == 1
    assert sum(report['rejected_tracks'].values()) == report['rejected']


def test_one_runtime_detection_cannot_represent_two_native_landmarks():
    data = fixture(points=((0., 0., 10.), (.0025, 0., 10.)))
    for view, (xy, desc) in enumerate(data[2]):
        data[2][view] = (xy[:1], desc[:1])
    valid, report = run(data)
    assert len(valid) == 1 and valid[0][1] == (0., 0., 10.)
    assert report['spatial_associations'] == 3
    assert report['landmark_provenance'][0]['native_point_id'] == 100


def test_native_spatial_ties_are_rejected_in_both_directions():
    data = fixture(points=((0., 0., 10.), (0., 0., 10.)))
    for view, (xy, desc) in enumerate(data[2]):
        data[2][view] = (xy[:1], desc[:1])
    valid, report = run(data)
    assert valid == [] and report['spatial_associations'] == 0


def test_actual_runtime_and_native_measurements_both_need_reprojection_support():
    data = fixture()
    # Preserve a unique exact native/runtime association, but contradict XYZ.
    data[0].images[1].points2D[0].xy[0] += 8
    data[2][0][0][0, 0] += 4
    valid, report = run(data)
    assert valid == [] and report['geometry_rejected_observations'] == 1


def test_nonpositive_depth_never_becomes_a_landmark():
    valid, report = run(fixture(points=((0., 0., -10.),)))
    assert valid == [] and report['geometry_rejected_observations'] == 3


def test_no_parallax_rejects_repeated_standing_frames():
    valid, report = run(fixture(centers=(0., 0., 0.)))
    assert valid == [] and report['rejected_tracks']['parallax'] == 1


def test_two_runtime_views_do_not_inherit_native_three_view_support():
    data = fixture()
    data[2][2] = (np.empty((0, 2)), np.empty((0, 128), np.float32))
    valid, report = run(data)
    assert valid == [] and report['rejected_tracks']['fewer_than_three_runtime_views'] == 1


def test_inconsistent_descriptors_do_not_get_an_average_invented_descriptor():
    data = fixture()
    for view, (_, desc) in enumerate(data[2]):
        desc[:] = 0
        desc[0, view] = 1
    valid, report = run(data)
    assert valid == [] and report['rejected_tracks']['descriptor_inconsistent'] == 1


def test_consistent_descriptor_support_is_recorded_without_outlier_view():
    data = fixture(centers=(-.5, 0., .5, 1.))
    data[2][3][1][:] = 0
    data[2][3][1][0, 127] = 1
    valid, report = run(data)
    assert valid[0][3] == (0, 1, 2)
    assert report['candidate_support_per_view'] == [1, 1, 1, 0]
    assert len(report['landmark_provenance'][0]['observations']) == 3


def test_returned_descriptor_is_medoid_of_final_shrunk_subset():
    vectors = np.asarray([[.61937473, .62542530, .47457153], [.92475459, .31082267, .21958649],
                          [.04205455, .49784731, .86624447], [.46485774, .88231645, .07365434],
                          [.42450252, .89674662, .12507239]])
    data = fixture(centers=(-1., -.5, 0., .5, 1.))
    for view, (_, desc) in enumerate(data[2]):
        desc[:] = 0
        desc[0, :3] = vectors[view]
    valid, report = run(data)
    assert valid[0][3] == (0, 3, 4)
    provenance = report['landmark_provenance'][0]
    assert provenance['medoid_observation']['view'] == 4
    samples = np.asarray([data[2][view][1][0] for view in valid[0][3]])
    distance = np.linalg.norm(samples[:, None] - samples[None, :], axis=2)
    np.testing.assert_array_equal(valid[0][2], samples[np.argmin(distance.sum(axis=1))])
    assert provenance['maximum_descriptor_distance'] <= .7


def test_pose_must_be_bound_to_reconstruction_not_only_caller_image():
    data = fixture()
    data[3][0] = data[3][0].copy()
    data[3][0][0, 3] += .1
    with pytest.raises(ValueError, match='pose_binding'):
        run(data)


def test_duplicate_native_image_observation_is_structural_rejection():
    data = fixture()
    data[0].points3D[100].track.elements.append(data[0].points3D[100].track.elements[0])
    with pytest.raises(ValueError, match='native_track_ambiguous'):
        run(data)


def test_native_track_row_must_be_reciprocal():
    data = fixture()
    data[0].images[1].points2D[0].point3D_id = 999
    with pytest.raises(ValueError, match='track_reciprocity'):
        run(data)


def test_image_feature_missing_from_its_points_track_is_rejected():
    data = fixture()
    source = data[0].images[1].points2D[0]
    data[0].images[1].points2D.append(SimpleNamespace(xy=source.xy.copy(), point3D_id=100,
                                                    has_point3D=lambda: True))
    with pytest.raises(ValueError, match='reverse_track_reciprocity'):
        run(data)


def test_native_track_row_must_exist_in_same_image_namespace():
    data = fixture()
    data[0].points3D[100].track.elements[0].point2D_idx = 3
    with pytest.raises(ValueError, match='row_binding'):
        run(data)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 1e20])
def test_invalid_native_xyz_is_rejected(value):
    data = fixture()
    data[0].points3D[100].xyz[0] = value
    with pytest.raises(ValueError, match='native_xyz'):
        run(data)


@pytest.mark.parametrize('bad', ['nan', 'zero', 'negative', 'shape', 'outside', 'not_normalized'])
def test_invalid_runtime_features_fail_closed(bad):
    data = fixture()
    xy, desc = data[2][0]
    if bad == 'nan':
        desc[0, 0] = np.nan
    elif bad == 'zero':
        desc[:] = 0
    elif bad == 'negative':
        desc[0, 0] = -1
    elif bad == 'shape':
        data[2][0] = (xy, desc[:, :127])
    elif bad == 'outside':
        xy[0, 0] = 960
    else:
        desc[0, 0] = .5
    with pytest.raises(ValueError, match='runtime_features'):
        run(data)


def test_spatial_comparison_quota_is_enforced(monkeypatch):
    monkeypatch.setattr(builder, 'MAX_SPATIAL_COMPARISONS', 0)
    with pytest.raises(ValueError, match='spatial_comparison_quota'):
        run(fixture())


def test_native_point_quota_is_enforced_before_scanning(monkeypatch):
    monkeypatch.setattr(builder, 'MAX_NATIVE_POINTS', 0)
    with pytest.raises(ValueError, match='input_quota'):
        run(fixture())


def test_view_and_feature_quota_are_enforced(monkeypatch):
    monkeypatch.setattr(builder, 'MAX_VIEWS', 2)
    with pytest.raises(ValueError, match='input_quota'):
        run(fixture())
    monkeypatch.setattr(builder, 'MAX_VIEWS', 256)
    monkeypatch.setattr(builder, 'MAX_RUNTIME_FEATURES_PER_VIEW', 0)
    with pytest.raises(ValueError, match='runtime_features'):
        run(fixture())


def test_time_quota_and_cancellation_propagate(monkeypatch):
    clock = iter([0., 61.])
    monkeypatch.setattr(builder.time, 'monotonic', lambda: next(clock))
    with pytest.raises(ValueError, match='time_quota'):
        run(fixture())


def test_checkpoint_cancels_before_geometry_processing():
    def stop():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        run(fixture(), stop)


def test_native_observation_quota_is_enforced(monkeypatch):
    monkeypatch.setattr(builder, 'MAX_NATIVE_OBSERVATIONS', 2)
    with pytest.raises(ValueError, match='native_observation_quota'):
        run(fixture())


def test_unused_native_rows_are_counted_before_any_traversal():
    class OversizedRows:
        def __len__(self):return builder.MAX_NATIVE_IMAGE_ROWS + 1
        def __iter__(self):raise AssertionError('must reject before iteration')
    data = fixture()
    data[0].images[1].points2D = OversizedRows()
    with pytest.raises(ValueError, match='native_image_row_quota'):
        run(data)


def test_reverse_unused_row_scan_has_chunked_cancellation_checkpoint():
    state = {'reverse_started': False}
    class Rows(list):
        def __iter__(self):
            state['reverse_started'] = True
            return super().__iter__()
    data = fixture()
    rows = Rows(data[0].images[1].points2D)
    rows.extend([SimpleNamespace(has_point3D=lambda: False)] * 4100)
    data[0].images[1].points2D = rows
    def stop_in_reverse():
        if state['reverse_started']:
            raise RuntimeError('cancelled_reverse')
    with pytest.raises(RuntimeError, match='cancelled_reverse'):
        run(data, stop_in_reverse)
