import hashlib
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot.route_fused_recovery import _seal_database
from scripts.pilot.route_intrinsics_prior import initialize_intrinsics
from scripts.pilot.route_native_track_policy import native_identity_signature


def fixture(tmp_path):
    path = tmp_path / "owned.db"
    camera = SimpleNamespace(
        model_name="SIMPLE_PINHOLE",
        width=200,
        height=100,
        params=np.array([100.0, 100.0, 50.0]),
        calibration_matrix=lambda: np.array(
            [[100.0, 0.0, 100.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]]
        ),
    )
    images, points, rows = {}, {}, []
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            "CREATE TABLE cameras(camera_id INTEGER,model INTEGER,width INTEGER,height INTEGER,params BLOB,prior_focal_length INTEGER);"
            "CREATE TABLE images(image_id INTEGER,name TEXT,camera_id INTEGER);"
            "CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE descriptors(image_id INTEGER,type INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE matches(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE two_view_geometries(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
        )
        db.execute(
            "INSERT INTO cameras VALUES(1,0,200,100,?,0)",
            (np.array([240.0, 100.0, 50.0], dtype="<f8").tobytes(),),
        )
        for identity in range(1, 13):
            matrix = np.column_stack([np.eye(3), [-identity * 0.1, 0.0, 0.0]])
            pose = SimpleNamespace(
                matrix=lambda m=matrix: m,
                rotation=SimpleNamespace(matrix=lambda: np.eye(3)),
                translation=matrix[:, 3],
            )
            features = []
            for point_id in range(1, 21):
                xyz = np.array([point_id * 0.05, 0.1, 10.0])
                local = xyz + matrix[:, 3]
                xy = (
                    ((camera.calibration_matrix() @ local)[:2] / local[2])
                    .astype("<f4")
                    .astype("<f8")
                )
                features.append(
                    SimpleNamespace(xy=xy, point3D_id=point_id, has_point3D=lambda: True)
                )
            name = f"{identity:08}.png"
            images[identity] = SimpleNamespace(
                name=name,
                image_id=identity,
                camera_id=1,
                points2D=features,
                num_points2D=lambda features=features: len(features),
                cam_from_world=lambda pose=pose: pose,
            )
            xy = np.asarray([point.xy for point in features], dtype="<f4")
            geometry = np.column_stack([xy, np.ones(len(xy)), np.zeros(len(xy))]).astype("<f4")
            db.execute("INSERT INTO images VALUES(?,?,1)", (identity, name))
            db.execute("INSERT INTO keypoints VALUES(?,20,4,?)", (identity, geometry.tobytes()))
            rows.append(
                dict(image="images/" + name, png_sha256=hashlib.sha256(name.encode()).hexdigest())
            )
        db.commit()
    for identity in range(1, 21):
        track = [
            SimpleNamespace(image_id=image_id, point2D_idx=identity - 1) for image_id in images
        ]
        points[identity] = SimpleNamespace(
            xyz=np.array([identity * 0.05, 0.1, 10.0]),
            color=np.array([100, 120, 140], dtype=np.uint8),
            error=0.0,
            track=SimpleNamespace(elements=track, length=lambda track=track: len(track)),
        )
    baseline = SimpleNamespace(
        cameras={1: camera}, images=images, points3D=points, reg_image_ids=lambda: list(images)
    )
    assessment = dict(
        scene_admissible=True,
        route_admissible=False,
        intrinsics_condition=dict(passed=True, physical_calibration_verified=False),
        observation_support=dict(
            status="complete", frame_count=12, summary=dict(min=20, count_under_15=0)
        ),
    )
    return path, baseline, assessment, rows


def invoke(path, baseline, assessment, rows, **kwargs):
    return initialize_intrinsics(
        path,
        baseline,
        assessment,
        rows,
        source_manifest_sha256="a" * 64,
        reconstruction_input_sha256="b" * 64,
        seal=_seal_database,
        **kwargs,
    )


def test_same_source_measured_intrinsics_change_only_owned_camera_and_keep_global_focal_free(
    tmp_path,
):
    path, baseline, assessment, rows = fixture(tmp_path)
    before = native_identity_signature(baseline)
    result = invoke(path, baseline, assessment, rows)
    assert result["applied"] and result["numerical_prior_only"]
    assert not result["physical_calibration_verified"] and not result["execution_qualified"]
    assert result["original_camera"]["params"] == [240.0, 100.0, 50.0]
    assert result["seeded_camera"]["params"] == [100.0, 100.0, 50.0]
    assert result["seeded_camera"]["prior_focal_length"] == 1
    assert result["global_focal_refinement"] and not result["poses_or_xyz_copied"]
    assert result["baseline_registered_views"] == 12
    assert (
        len(result["baseline_semantic_sha256"]) == 64
        and len(result["baseline_assessment_sha256"]) == 64
    )
    assert result["source_manifest_sha256"] == "a" * 64
    assert result["baseline_actual_observation_audit"]["minimum_camera_support_4px"] == 20
    assert native_identity_signature(baseline) == before
    with closing(sqlite3.connect(path)) as db:
        params, prior = db.execute("SELECT params,prior_focal_length FROM cameras").fetchone()
        assert np.frombuffer(params, "<f8").tolist() == [100.0, 100.0, 50.0] and prior == 1
        assert db.execute("SELECT count(*) FROM keypoints").fetchone()[0] == 12


@pytest.mark.parametrize(
    "kind",
    [
        "camera_model",
        "resolution",
        "image_name",
        "image_id",
        "image_camera",
        "nan",
        "principal",
        "source_rows",
        "xy_namespace",
        "no_scene",
        "no_support",
        "actual_bad_support",
    ],
)
def test_unreliable_or_different_source_model_declines_without_modifying_database(tmp_path, kind):
    path, baseline, assessment, rows = fixture(tmp_path)
    if kind == "camera_model":
        baseline.cameras[1].model_name = "PINHOLE"
    elif kind == "resolution":
        baseline.cameras[1].width = 201
    elif kind == "image_name":
        baseline.images[1].name = "foreign.png"
    elif kind == "image_id":
        baseline.images[99] = baseline.images.pop(1)
    elif kind == "image_camera":
        baseline.images[1].camera_id = 2
    elif kind == "nan":
        baseline.cameras[1].params[0] = np.nan
    elif kind == "principal":
        baseline.cameras[1].params[-1] += 1.0
    elif kind == "source_rows":
        rows[0]["image"] = "images/foreign.png"
    elif kind == "xy_namespace":
        baseline.images[1].points2D[0].xy[0] += 1.0
    elif kind == "no_scene":
        assessment["scene_admissible"] = False
    elif kind == "no_support":
        assessment["observation_support"]["summary"]["min"] = 14
    else:
        baseline.points3D[1].xyz[0] += 100.0
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = invoke(path, baseline, assessment, rows)
    assert result["applied"] is False and result["reason"].startswith("intrinsics_")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_no_baseline_and_cancellation_do_not_turn_default_guess_into_calibration(tmp_path):
    path, baseline, assessment, rows = fixture(tmp_path)
    before = path.read_bytes()
    assert invoke(path, None, None, rows)["reason"] == "intrinsics_baseline_missing"

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        invoke(path, baseline, assessment, rows, check=cancelled)
    assert path.read_bytes() == before
