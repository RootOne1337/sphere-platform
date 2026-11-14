from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import route_native_track_policy as policy


def model():
    camera = SimpleNamespace(
        model_name="SIMPLE_PINHOLE",
        width=200,
        height=100,
        params=np.array([100.0, 100.0, 50.0]),
        calibration_matrix=lambda: np.array(
            [[100.0, 0.0, 100.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]]
        ),
    )
    images = {}
    points = {}
    for image_id in range(1, 5):
        matrix = np.column_stack([np.eye(3), [-image_id * 0.1, 0.0, 0.0]])
        pose = SimpleNamespace(
            matrix=lambda m=matrix: m,
            rotation=SimpleNamespace(matrix=lambda: np.eye(3)),
            translation=matrix[:, 3],
        )
        features = []
        for point_id in range(1, 21):
            xyz = np.array([point_id * 0.05, 0.1, 10.0])
            local = xyz + matrix[:, 3]
            xy = (camera.calibration_matrix() @ local)[:2] / local[2]
            features.append(SimpleNamespace(xy=xy, point3D_id=point_id, has_point3D=lambda: True))
        images[image_id] = SimpleNamespace(
            name=f"{image_id:08}.png",
            image_id=image_id,
            camera_id=1,
            points2D=features,
            num_points2D=lambda f=features: len(f),
            cam_from_world=lambda p=pose: p,
        )
    for point_id in range(1, 21):
        elements = [SimpleNamespace(image_id=i, point2D_idx=point_id - 1) for i in images]
        points[point_id] = SimpleNamespace(
            xyz=np.array([point_id * 0.05, 0.1, 10.0]),
            color=np.array([100, 120, 140], dtype=np.uint8),
            error=0.0,
            track=SimpleNamespace(elements=elements, length=lambda el=elements: len(el)),
        )

    def drop(point_id):
        del points[point_id]
        for image in images.values():
            for feature in image.points2D:
                if feature.point3D_id == point_id:
                    feature.point3D_id = -1
                    feature.has_point3D = lambda: False

    return SimpleNamespace(
        cameras={1: camera},
        images=images,
        points3D=points,
        delete_point3D=drop,
        reg_image_ids=lambda: list(images),
    )


def test_native_identity_binds_both_directions_even_when_camera_xy_and_xyz_are_equal():
    rec = model()
    before = policy.native_identity_signature(rec)
    rec.images[1].points2D[0].point3D_id = 2
    assert policy.measurement_signature(rec) == {
        key: before[key] for key in ("cameras", "images", "xyz")
    }
    assert policy.native_identity_signature(rec) != before
    rec.images[1].points2D[0].point3D_id = 1
    rec.points3D[1].track.elements[0].point2D_idx = 1
    assert policy.native_identity_signature(rec) != before


def test_uniformly_removes_every_duplicate_image_and_under_three_view_track_without_editing_measurements():
    rec = model()
    rec.points3D[1].track.elements.append(SimpleNamespace(image_id=1, point2D_idx=0))
    rec.points3D[2].track.elements[:] = rec.points3D[2].track.elements[:2]
    # Remove the reverse associations as a real 2-view native track would.
    for identity in (3, 4):
        rec.images[identity].points2D[1].point3D_id = -1
        rec.images[identity].points2D[1].has_point3D = lambda: False
    before = policy.measurement_signature(rec)
    report = policy.filter_whole_tracks(rec)
    assert report["removed_count"] == 2
    assert {r["reason"] for r in report["removed"]} == {"repeated_image", "below_3_views"}
    assert set(rec.points3D) == set(range(3, 21))
    after = policy.measurement_signature(rec)
    assert before["cameras"] == after["cameras"] and before["images"] == after["images"]
    assert {i: value for i, value in before["xyz"].items() if i not in {1, 2}} == after["xyz"]


@pytest.mark.parametrize("kind", ["wrong_id", "bad_row", "bad_reciprocal", "nan_xyz"])
def test_invalid_native_measurements_are_refused_instead_of_cosmetically_filtered(kind):
    rec = model()
    if kind == "wrong_id":
        rec.points3D[1].track.elements[0].image_id = 99
    elif kind == "bad_row":
        rec.points3D[1].track.elements[0].point2D_idx = 99
    elif kind == "bad_reciprocal":
        rec.images[1].points2D[0].point3D_id = 99
    else:
        rec.points3D[1].xyz[0] = np.nan
    with pytest.raises(ValueError, match="native_track_"):
        policy.filter_whole_tracks(rec)


def test_actual_observation_audit_does_not_trust_low_cached_point_errors():
    rec = model()
    report = policy.audit_native_model(rec)
    assert report["minimum_camera_support_4px"] == 20
    assert report["actual_reprojection_px"]["maximum"] < 1e-10
    for image in rec.images.values():
        for feature in image.points2D:
            feature.xy += [20.0, 0.0]
    assert all(point.error == 0.0 for point in rec.points3D.values())
    with pytest.raises(ValueError, match="native_track_measured_support_failed"):
        policy.audit_native_model(rec)


def test_cross_family_same_pixel_rows_do_not_inflate_independent_camera_support():
    rec = model()
    for point_id in range(11, 21):
        rec.points3D[point_id].xyz = rec.points3D[point_id - 10].xyz.copy()
        for image in rec.images.values():
            image.points2D[point_id - 1].xy = image.points2D[point_id - 11].xy.copy()
    assert policy.filter_whole_tracks(rec)["removed_count"] == 0
    # Every raw row has a valid reciprocal track, positive depth and zero
    # residual, but 20 raw rows measure only ten independent pixels/camera.
    with pytest.raises(ValueError, match="native_track_measured_support_failed"):
        policy.audit_native_model(rec)


def test_physical_pixel_aliases_are_measured_without_editing_rows_or_points():
    rec = model()
    for point_id in range(16, 21):
        rec.points3D[point_id].xyz = rec.points3D[point_id - 15].xyz.copy()
        for image in rec.images.values():
            image.points2D[point_id - 1].xy = image.points2D[point_id - 16].xy.copy()
    before = policy.native_identity_signature(rec)
    report = policy.audit_native_model(rec)
    assert report["observations"] == 80 and report["physical_camera_observations"] == 60
    assert report["cross_landmark_exact_pixel_alias_rows"] == 20
    assert report["minimum_camera_support_4px"] == 15
    assert report["support_policy"] == "unique_exact_xy_per_camera_worst_residual"
    assert policy.native_identity_signature(rec) == before


def test_policy_propagates_cancellation_before_mutating_any_track():
    rec = model()

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        policy.filter_whole_tracks(rec, check=cancelled)
    assert len(rec.points3D) == 20


def test_changed_camera_or_xy_during_native_deletion_is_rejected():
    rec = model()
    rec.points3D[1].track.elements.append(SimpleNamespace(image_id=1, point2D_idx=0))
    original = rec.delete_point3D

    def mutate(point_id):
        original(point_id)
        rec.cameras[1].params[0] += 1.0

    rec.delete_point3D = mutate
    with pytest.raises(ValueError, match="native_track_filter_changed_measurements"):
        policy.filter_whole_tracks(rec)
