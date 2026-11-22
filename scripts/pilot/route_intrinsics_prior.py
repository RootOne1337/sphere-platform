"""Same-source measured SfM intrinsics as a numerical global-SfM initializer.

No physical calibration or route geometry is copied. A declined initialization
leaves the owned database unchanged; global focal optimization remains free.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
from contextlib import closing
from pathlib import Path


def _hash(path, check):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while value := stream.read(1024**2):
            check()
            result.update(value)
    return result.hexdigest()


def _json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _measurements(database, check):
    result = {}
    for table in ("images", "keypoints", "matches", "two_view_geometries", "descriptors"):
        value = hashlib.sha256()
        count = 0
        for row in database.execute("SELECT * FROM " + table + " ORDER BY 1"):
            if count % 128 == 0:
                check()
            count += 1
            for item in row:
                data = (
                    b"B" + item
                    if isinstance(item, bytes)
                    else b"N"
                    if item is None
                    else b"S" + item.encode()
                    if isinstance(item, str)
                    else b"I" + str(item).encode()
                )
                value.update(struct.pack("<Q", len(data)))
                value.update(data)
        result[table] = dict(rows=count, sha256=value.hexdigest())
    return result


def initialize_intrinsics(
    database,
    baseline,
    assessment,
    rows,
    *,
    source_manifest_sha256,
    reconstruction_input_sha256,
    seal,
    check=lambda: None,
):
    """Modify only one owned camera row after proving the shared observation space."""
    import numpy as np

    from scripts.pilot.route_native_track_policy import (
        audit_native_model,
        native_identity_signature,
    )

    database = Path(database)
    report = dict(
        schema="sphere-same-source-sfm-intrinsics-prior-v1",
        applied=False,
        physical_calibration_verified=False,
        execution_qualified=False,
        numerical_prior_only=True,
        global_focal_refinement=True,
        source_manifest_sha256=source_manifest_sha256,
        reconstruction_input_sha256=reconstruction_input_sha256,
        producer_sha256=_hash(Path(__file__), check),
    )
    if baseline is None:
        return dict(report, reason="intrinsics_baseline_missing")
    if not isinstance(assessment, dict):
        return dict(report, reason="intrinsics_baseline_unqualified")
    support = assessment.get("observation_support") or {}
    if not isinstance(support, dict):
        return dict(report, reason="intrinsics_baseline_unqualified")
    summary = support.get("summary") or {}
    if not isinstance(summary, dict):
        return dict(report, reason="intrinsics_baseline_unqualified")
    if (
        not isinstance(assessment, dict)
        or assessment.get("scene_admissible") is not True
        or (assessment.get("intrinsics_condition") or {}).get("passed") is not True
        or support.get("status") != "complete"
        or type(summary.get("min")) not in (int, float)
        or not math.isfinite(summary["min"])
        or summary["min"] < 15
        or summary.get("count_under_15") != 0
    ):
        return dict(report, reason="intrinsics_baseline_unqualified")
    before_sha = _hash(database, check)
    try:
        ids = sorted(int(value) for value in baseline.reg_image_ids())
        if (
            not 10 <= len(ids) <= 240
            or support.get("frame_count") != len(ids)
            or len(baseline.cameras) != 1
        ):
            raise ValueError("intrinsics_baseline_camera_namespace")
        source = {Path(row["image"]).name: row["png_sha256"] for row in rows}
        if len(source) != len(rows):
            raise ValueError("intrinsics_source_namespace")
        with closing(sqlite3.connect(database)) as connection:
            cameras = connection.execute(
                "SELECT camera_id,model,width,height,params,prior_focal_length FROM cameras"
            ).fetchall()
            links = connection.execute(
                "SELECT image_id,name,camera_id FROM images ORDER BY image_id"
            ).fetchall()
            if len(cameras) != 1:
                raise ValueError("intrinsics_database_camera_namespace")
            camera_id, model, width, height, raw, old_prior = cameras[0]
            if (
                set(source) != {row[1] for row in links}
                or len(links) != len(source)
                or any(row[2] != camera_id for row in links)
            ):
                raise ValueError("intrinsics_source_namespace")
            if set(baseline.cameras) != {camera_id}:
                raise ValueError("intrinsics_baseline_camera_namespace")
            camera = baseline.cameras[camera_id]
            layout = {0: ("SIMPLE_PINHOLE", 3), 1: ("PINHOLE", 4)}.get(model)
            parameters = np.asarray(camera.params, dtype="<f8")
            old = np.frombuffer(raw, dtype="<f8")
            if (
                layout is None
                or camera.model_name != layout[0]
                or parameters.shape != (layout[1],)
                or old.shape != parameters.shape
            ):
                raise ValueError("intrinsics_projection_mismatch")
            if camera.width != width or camera.height != height:
                raise ValueError("intrinsics_resolution_mismatch")
            if (
                not np.isfinite(parameters).all()
                or not np.isfinite(old).all()
                or np.any(parameters[:-2] <= 0)
            ):
                raise ValueError("intrinsics_nonfinite_or_nonpositive")
            if not np.array_equal(parameters[-2:], old[-2:]):
                raise ValueError("intrinsics_principal_point_mismatch")
            by_id = {row[0]: (row[1], row[2]) for row in links}
            measured = []
            for identity in ids:
                check()
                image = baseline.images[identity]
                if (
                    by_id.get(identity) != (image.name, int(image.camera_id))
                    or image.camera_id != camera_id
                ):
                    raise ValueError("intrinsics_image_identity_mismatch")
                count, columns, blob = connection.execute(
                    "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (identity,)
                ).fetchone()
                actual = np.asarray([point.xy for point in image.points2D], dtype="<f8").reshape(
                    -1, 2
                )
                if columns != 4 or len(blob) != count * columns * 4 or len(actual) > count:
                    raise ValueError("intrinsics_feature_namespace")
                expected = (
                    np.frombuffer(blob, dtype="<f4")
                    .reshape(count, columns)[: len(actual), :2]
                    .astype("<f8")
                )
                if not np.array_equal(actual, expected):
                    raise ValueError("intrinsics_feature_namespace")
                measured.append(
                    dict(
                        image_id=identity,
                        image=image.name,
                        camera_id=camera_id,
                        measured_rows=len(actual),
                        xy_sha256=hashlib.sha256(actual.tobytes()).hexdigest(),
                        source_png_sha256=source[image.name],
                    )
                )
            # Recompute physical-pixel support; do not accept persisted counters
            # or duplicate VIDEO/SIFT rows as independent measurements.
            native_audit = audit_native_model(baseline, check=check)
            semantic = native_identity_signature(baseline, check=check)
            fingerprint = _measurements(connection, check)
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE cameras SET params=?,prior_focal_length=1 WHERE camera_id=?",
                (parameters.tobytes(), camera_id),
            )
            if updated.rowcount != 1 or _measurements(connection, check) != fingerprint:
                connection.rollback()
                raise ValueError("intrinsics_changed_measurements")
            connection.commit()
        seal(database)
        report.update(
            applied=True,
            reason="intrinsics_same_source_sfm_numeric_prior",
            source_database_sha256=before_sha,
            seeded_database_sha256=_hash(database, check),
            original_camera=dict(
                camera_id=int(camera_id),
                model=int(model),
                width=int(width),
                height=int(height),
                params=old.tolist(),
                prior_focal_length=int(old_prior),
            ),
            seeded_camera=dict(
                camera_id=int(camera_id),
                model=int(model),
                width=int(width),
                height=int(height),
                params=parameters.tolist(),
                prior_focal_length=1,
            ),
            prior_flag_semantics="same_source_measured_sfm_initialization_not_physical_calibration",
            baseline_registered_views=len(ids),
            baseline_semantic_sha256=_json_hash(semantic),
            baseline_assessment=assessment,
            baseline_assessment_sha256=_json_hash(assessment),
            image_measurement_binding_sha256=_json_hash(measured),
            non_camera_measurements=fingerprint,
            baseline_actual_observation_audit=native_audit,
            poses_or_xyz_copied=False,
            source_images_unchanged=True,
        )
        return report
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        if _hash(database, check) != before_sha:
            raise ValueError("intrinsics_declined_after_database_change") from error
        return dict(
            report,
            reason=str(error)
            if str(error).startswith("intrinsics_")
            else "intrinsics_baseline_invalid",
        )
