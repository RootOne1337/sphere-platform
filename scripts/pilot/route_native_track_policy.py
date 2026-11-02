"""Uniform native-track filtering on an owned camera-model clone.

Whole tracks are removed by support/identity, never to smooth a plotted route.
Filtering preserves every pose, intrinsic, 2D pixel and retained 3D position.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

MAX_IMAGES = 240
MAX_POINTS = 100_000
MAX_OBSERVATIONS = 2_000_000


def _array_hash(value):
    import numpy as np

    array = np.asarray(value)
    if not np.isfinite(array).all():
        raise ValueError("native_track_nonfinite_measurement")
    return hashlib.sha256(array.tobytes()).hexdigest()


def measurement_signature(rec, *, check=lambda: None):
    """Bind measured data without relying on derived point error caches."""
    import numpy as np

    ids = sorted(rec.reg_image_ids())
    if not 3 <= len(ids) <= MAX_IMAGES or len(rec.points3D) > MAX_POINTS:
        raise ValueError("native_track_model_quota")
    cameras = {
        int(i): (c.model_name, c.width, c.height, _array_hash(c.params))
        for i, c in rec.cameras.items()
    }
    images, total = {}, 0
    for identity in ids:
        check()
        image = rec.images[identity]
        total += len(image.points2D)
        if total > MAX_OBSERVATIONS:
            raise ValueError("native_track_observation_quota")
        xy = np.asarray([v.xy for v in image.points2D], dtype=np.float64).reshape(-1, 2)
        images[int(identity)] = (
            image.name,
            int(image.camera_id),
            _array_hash(image.cam_from_world().matrix()),
            _array_hash(xy),
        )
    xyz = {}
    for n, (identity, point) in enumerate(rec.points3D.items()):
        if n % 256 == 0:
            check()
        xyz[int(identity)] = _array_hash(point.xyz)
    return dict(cameras=cameras, images=images, xyz=xyz)


def native_identity_signature(rec, *, check=lambda: None):
    """Include native association identities when selecting a frozen model.

    Equal poses/XYZ alone cannot prove that a descriptor row still names the
    same landmark. This adds every reverse association and ordered track to
    the measured signature. Derived error/color data is included so a frozen
    serialization is reused only for the unchanged chosen reconstruction.
    """
    import numpy as np

    signature = measurement_signature(rec, check=check)
    associations, tracks, attributes = {}, {}, {}
    for identity in sorted(rec.reg_image_ids()):
        check()
        associations[int(identity)] = _array_hash(
            np.asarray(
                [
                    int(point.point3D_id) if point.has_point3D() else -1
                    for point in rec.images[identity].points2D
                ],
                dtype=np.int64,
            )
        )
    for n, (identity, point) in enumerate(rec.points3D.items()):
        if n % 256 == 0:
            check()
        tracks[int(identity)] = _array_hash(
            np.asarray(
                [(int(row.image_id), int(row.point2D_idx)) for row in point.track.elements],
                dtype=np.int64,
            ).reshape(-1, 2)
        )
        attributes[int(identity)] = (_array_hash(point.color), _array_hash([point.error]))
    return dict(**signature, associations=associations, tracks=tracks, attributes=attributes)


def filter_whole_tracks(rec, *, minimum_views=3, check=lambda: None):
    """Mutate only an owned clone; reject invalid reciprocity rather than fix it."""
    if minimum_views != 3:
        raise ValueError("native_track_support_policy")
    before = measurement_signature(rec, check=check)
    ids, removed, total = set(rec.reg_image_ids()), [], 0
    for n, (identity, point) in enumerate(rec.points3D.items()):
        if n % 256 == 0:
            check()
        elements = list(point.track.elements)
        if len(elements) != point.track.length():
            raise ValueError("native_track_length_invalid")
        total += len(elements)
        if total > MAX_OBSERVATIONS:
            raise ValueError("native_track_observation_quota")
        seen, duplicate = set(), False
        for element in elements:
            image_id, row = int(element.image_id), int(element.point2D_idx)
            if image_id not in ids or not 0 <= row < len(rec.images[image_id].points2D):
                raise ValueError("native_track_element_invalid")
            feature = rec.images[image_id].points2D[row]
            if not feature.has_point3D() or int(feature.point3D_id) != int(identity):
                raise ValueError("native_track_reciprocity_invalid")
            duplicate |= image_id in seen
            seen.add(image_id)
        if duplicate or len(seen) < minimum_views:
            removed.append(
                dict(
                    point_id=int(identity),
                    reason="repeated_image" if duplicate else "below_3_views",
                    observations=len(elements),
                    distinct_views=len(seen),
                )
            )
    for item in removed:
        rec.delete_point3D(item["point_id"])
    after = measurement_signature(rec, check=check)
    dropped = {item["point_id"] for item in removed}
    if (
        before["cameras"] != after["cameras"]
        or before["images"] != after["images"]
        or {i: value for i, value in before["xyz"].items() if i not in dropped} != after["xyz"]
    ):
        raise ValueError("native_track_filter_changed_measurements")
    return dict(
        schema="sphere-native-whole-track-policy-v1",
        minimum_views=3,
        policy="drop_entire_track_if_repeated_image_or_below_3_registered_views",
        removed=removed,
        removed_count=len(removed),
        retained_points=len(rec.points3D),
        poses_intrinsics_all_xy_retained_xyz_unchanged=True,
        execution_qualified=False,
    )


def audit_native_model(rec, *, check=lambda: None):
    """Strict reciprocal/positive-depth structure and actual observed residuals."""
    import numpy as np

    from scripts.pilot.route_component_merge import structural_audit

    structural = structural_audit(rec, check=check)
    residuals, physical_residuals, support = [], [], []
    for identity in rec.reg_image_ids():
        check()
        image = rec.images[identity]
        camera = rec.cameras[image.camera_id]
        if camera.model_name not in {"SIMPLE_PINHOLE", "PINHOLE"}:
            raise ValueError("native_track_camera_model")
        pairs = [(rec.points3D[v.point3D_id].xyz, v.xy) for v in image.points2D if v.has_point3D()]
        if not pairs:
            raise ValueError("native_track_empty_camera")
        xyz, observed = np.asarray([p[0] for p in pairs]), np.asarray([p[1] for p in pairs])
        matrix = np.asarray(image.cam_from_world().matrix())
        local = xyz @ matrix[:, :3].T + matrix[:, 3]
        projected = local @ np.asarray(camera.calibration_matrix()).T
        projected = projected[:, :2] / projected[:, 2:3]
        errors = np.linalg.norm(projected - observed, axis=1)
        if not np.isfinite(errors).all():
            raise ValueError("native_track_projection_invalid")
        residuals.extend(errors.tolist())
        # VIDEO and SIFT rows can measure the exact same physical pixel while
        # retaining separate namespaces. They are one support observation.
        # Use the worst error per pixel; duplicates cannot improve admission.
        physical = {}
        for xy, error in zip(observed, errors):
            key = xy.astype("<f8").tobytes()
            physical[key] = max(physical.get(key, 0.0), float(error))
        unique_errors = np.asarray(list(physical.values()))
        physical_residuals.extend(unique_errors.tolist())
        support.append(int((unique_errors <= 4.0).sum()))

    def summary(values):
        values = np.asarray(values)
        return dict(
            mean=float(values.mean()),
            median=float(np.median(values)),
            p95=float(np.percentile(values, 95)),
            maximum=float(values.max()),
        )

    measured = summary(physical_residuals)
    if (
        min(support) < 15
        or measured["mean"] > 3.0
        or measured["p95"] > 4.0
        or measured["maximum"] > 8.0
    ):
        raise ValueError("native_track_measured_support_failed")
    return dict(
        structural=structural,
        actual_reprojection_px=measured,
        raw_native_reprojection_px=summary(residuals),
        minimum_camera_support_4px=min(support),
        observations=len(residuals),
        physical_camera_observations=len(physical_residuals),
        cross_landmark_exact_pixel_alias_rows=len(residuals) - len(physical_residuals),
        support_policy="unique_exact_xy_per_camera_worst_residual",
        execution_qualified=False,
    )


def bundle_adjust(input_model, output_model):
    """Only invoked by the separately owned, externally timed CPU child."""
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / ".local-pilot/reconstruction-tools/pycolmap-4.2.1"))
    import pycolmap as p

    if p.__version__ != "4.2.1":
        raise ValueError("native_track_pycolmap_version")
    rec = p.Reconstruction(input_model)
    options = p.BundleAdjustmentOptions()
    options.refine_focal_length = options.refine_principal_point = options.refine_extra_params = (
        False
    )
    options.refine_sensor_from_rig = False
    options.min_track_length = 3
    options.ceres.loss_function_type = p.LossFunctionType.SOFT_L1
    options.ceres.loss_function_scale = 2.0
    options.ceres.use_gpu = False
    options.ceres.solver_options.num_threads = 2
    options.ceres.solver_options.max_solver_time_in_seconds = 50.0
    options.ceres.solver_options.max_num_iterations = 100
    Path(output_model).mkdir()
    p.bundle_adjustment(rec, options)
    rec.write(output_model)


def verify(database, pairs):
    """Pinned native verifier, called only inside an owned deadline child."""
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / ".local-pilot/reconstruction-tools/pycolmap-4.2.1"))
    import pycolmap as p

    if p.__version__ != "4.2.1":
        raise ValueError("native_track_pycolmap_version")
    options = p.TwoViewGeometryOptions()
    options.ransac.num_threads = 1
    options.ransac.random_seed = 17
    options.ransac.max_num_trials = 2000
    options.filter_stationary_matches = False
    p.verify_matches(database, pairs, options=options, cancellation_token=p.CancellationToken())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-adjust", nargs=2, metavar=("INPUT", "OUTPUT"), required=True)
    args = parser.parse_args()
    bundle_adjust(*args.bundle_adjust)
