import json
import uuid
from types import SimpleNamespace

import numpy as np
import pytest

from motor_worker import route_reference_lk as lk
from motor_worker.route_localization import RoutePose, pipeline_id
from motor_worker.vehicle_route import VehicleRouteFollower
from motor_worker.walk_route import WalkRouteFollower
from scripts.pilot import route_reference_lk_export as export
from tests.test_route_reference_lk import digest, loaded


def test_typed_reference_route_integrates_finite_walk_and_vehicle_plans_without_input(tmp_path):
    route, _, _ = loaded(tmp_path)
    try:
        walk = WalkRouteFollower(route, clock=lambda: 1.0)
        vehicle = VehicleRouteFollower(
            route,
            SimpleNamespace(sample=lambda *_: None),
            clock=lambda: 1.0,
            reference_rotations=[np.eye(3)] * 3,
        )
        pose = RoutePose(
            "unknown",
            "route_pose_not_verified",
            route.id,
            route.world_revision,
            str(uuid.uuid4()),
            1,
            1.0,
            1.0,
            "a" * 64,
            (960, 540),
        )
        assert walk.observe(pose)["stick"] == [0.0, 0.0]
        reply = vehicle.observe(pose, None)
        assert reply["pedal"] == "coast" and reply["steering"] == 0.0
        assert reply["executionQualified"] is False
    finally:
        route.close()


def test_new_family_pursuit_acquires_fresh_geometry_and_neutralizes_lost_pose(tmp_path):
    route, _, _ = loaded(tmp_path)
    now, epoch = [10.0], str(uuid.uuid4())
    try:
        # The measured unit fixture moves along world +X. Match its view to
        # that direction rather than testing the controller's turn-in-place gate.
        rotation = np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
        walk = WalkRouteFollower(route, clock=lambda: now[0])
        vehicle = VehicleRouteFollower(
            route,
            SimpleNamespace(sample=lambda *_: 12.0, preview=lambda *_, **__: 12.0),
            clock=lambda: now[0],
            reference_rotations=[rotation] * len(route.camera_trace),
        )
        for sequence in range(1, 4):
            pose = RoutePose(
                "localized",
                "relative_camera_pose_not_clearance_or_arrival",
                route.id,
                route.world_revision,
                epoch,
                sequence,
                now[0],
                now[0],
                str(sequence) * 64,
                (960, 540),
                center=(0.0, 0.0, 0.0),
                rotation=tuple(rotation.flat),
                segment=0,
                progress_units=0.0,
                cross_track_units=0.0,
                inliers=40,
                median_error_px=0.5,
            )
            speed = dict(
                status="accepted",
                speed_kmh=4.0,
                confidence=95.0,
                epoch=epoch,
                sequence=sequence,
                received_at=now[0],
                source_rgb_sha256=pose.source_rgb_sha256,
            )
            walking, driving = walk.observe(pose), vehicle.observe(pose, speed)
            now[0] += 0.1
        assert walking["phase"] == driving["phase"] == "following"
        assert any(walking["stick"]) and driving["pedal"] == "throttle"
        unknown = RoutePose(
            "unknown",
            "route_pose_not_verified",
            route.id,
            route.world_revision,
            epoch,
            4,
            now[0],
            now[0],
            "4" * 64,
            (960, 540),
        )
        assert walk.observe(unknown)["stick"] == [0.0, 0.0]
        stopped = vehicle.observe(unknown, None)
        assert stopped["pedal"] == "coast" and stopped["steering"] == 0.0
        assert stopped["executionQualified"] is False
    finally:
        route.close()


def qualification_fixture(folder):
    route, path, data = loaded(folder)
    try:
        receipt = dict(
            schema=export.RECEIPT_SCHEMA,
            family=lk.FAMILY,
            sha256=digest(path),
            pipeline_sha256=lk.reference_lk_pipeline_id(),
            cache_file=lk.CACHE_FILE,
            cache_sha256=data["cache_sha256"],
            source_capture_sha256=data["source_capture_sha256"],
            source_index_sha256=data["source_index_sha256"],
            geometry_sha256=data["source_geometry_sha256"],
            model_sha256=dict(data["model_sha256"]),
            map_support=lk.reference_lk_support(route),
            execution_qualified=False,
        )
    finally:
        route.close()
    binding = dict(
        schema="sphere-route-preparation-source-v1",
        kind="alternative",
        alternative_id="known-good",
        geometry_sha256=receipt["geometry_sha256"],
        source_manifest_sha256=receipt["source_capture_sha256"],
        reconstruction_input_sha256=receipt["source_index_sha256"],
        model_sha256=receipt["model_sha256"],
    )
    q = dict(
        schema=export.QUALIFICATION_SCHEMA,
        scope="controlled_experimental_test_only",
        reviewed=True,
        execution_qualified=False,
        route_sha256=receipt["sha256"],
        cache_sha256=receipt["cache_sha256"],
        pipeline_sha256=lk.reference_lk_pipeline_id(),
        source_binding_sha256=lk.canonical_hash(binding),
    )
    reports = {}
    for name, kind in (
        ("positive", "same_recording_heldout"),
        ("transport", "same_recording_heldout_transport"),
        ("negative", "unrelated_negative"),
    ):
        rows = [
            dict(
                source_index=1,
                source_rgb_sha256="6" * 64,
                actualdecoded_rgb_sha256="4" * 64,
                state="unknown" if name == "negative" else "localized",
                compute_ms=40.0,
                diagnostic=dict(method="measured_reference_lk"),
            )
        ]
        if name == "transport":
            rows[0]["jpeg_sha256"] = "7" * 64
        report = dict(
            schema=export.VALIDATION_SCHEMA,
            kind=kind,
            route_sha256=receipt["sha256"],
            cache_sha256=receipt["cache_sha256"],
            pipeline_sha256=lk.reference_lk_pipeline_id(),
            source_capture_sha256="f" * 64
            if name == "negative"
            else receipt["source_capture_sha256"],
            sample_count=1,
            counts={rows[0]["state"]: 1},
            sample_rows=rows,
            offline_media_clock=name != "transport",
            execution_qualified=False,
            untaught_source_indices=True,
            raw_rgb_source_bound=True,
            unrelated_sources=True,
            false_pose_count=0,
            freshness_lower_bound=dict(
                receiver_age_budget_ms=250,
                samples_exceeding_budget=0,
                localized_samples_exceeding_budget=0,
            ),
        )
        if name == "transport":
            report["transport"] = dict(codec="jpeg", quality=86, width=960, height=540)
        reports[name] = report
    return receipt, binding, q, reports


def seal_qualification(folder, q, reports):
    for name, report in reports.items():
        path = folder / f"reference-lk-{name}.json"
        path.write_text(json.dumps(report), encoding="utf8")
        q[name + "_report"] = dict(file=path.name, sha256=digest(path))
    (folder / "controlled-test-qualification.json").write_text(json.dumps(q), encoding="utf8")


def test_exported_artifact_alone_cannot_authorize_controlled_test(tmp_path):
    receipt, binding, _, _ = qualification_fixture(tmp_path)
    with pytest.raises(ValueError, match="unqualified"):
        export.validate_reference_lk_qualification(receipt, tmp_path, source_binding=binding)


@pytest.mark.parametrize(
    "kind",
    [
        "unreviewed",
        "autonomy",
        "source",
        "pipeline",
        "negative_pose",
        "negative_known_image",
        "counts",
        "taught",
        "transport_missing",
        "transport_indices",
        "transport_quality",
        "transport_virtual_clock",
        "raw_wall_clock",
        "transport_no_pose",
        "freshness",
    ],
)
def test_controlled_qualification_requires_actual_bound_raw_jpeg_and_unrelated_negative_evidence(
    tmp_path, kind
):
    receipt, binding, q, reports = qualification_fixture(tmp_path)
    if kind == "unreviewed":
        q["reviewed"] = False
    if kind == "autonomy":
        q["execution_qualified"] = True
    if kind == "source":
        q["source_binding_sha256"] = "0" * 64
    if kind == "pipeline":
        q["pipeline_sha256"] = pipeline_id()
    if kind == "negative_pose":
        reports["negative"]["counts"] = {"confirming": 1}
        reports["negative"]["sample_rows"][0]["state"] = "confirming"
    if kind == "negative_known_image":
        reports["negative"]["sample_rows"][0]["actualdecoded_rgb_sha256"] = "1" * 64
    if kind == "counts":
        reports["positive"]["counts"]["localized"] = 2
    if kind == "taught":
        reports["positive"]["sample_rows"][0]["source_index"] = 0
    if kind == "transport_indices":
        reports["transport"]["sample_rows"][0]["source_index"] = 2
    if kind == "transport_quality":
        reports["transport"]["transport"]["quality"] = 60
    if kind == "transport_virtual_clock":
        reports["transport"]["offline_media_clock"] = True
    if kind == "raw_wall_clock":
        reports["positive"]["offline_media_clock"] = False
    if kind == "transport_no_pose":
        reports["transport"]["counts"] = {"unknown": 1}
        reports["transport"]["sample_rows"][0]["state"] = "unknown"
    if kind == "freshness":
        reports["positive"]["sample_rows"][0]["compute_ms"] = 500.0
    seal_qualification(tmp_path, q, reports)
    if kind == "transport_missing":
        (tmp_path / "reference-lk-transport.json").unlink()
    with pytest.raises((ValueError, OSError)):
        export.validate_reference_lk_qualification(receipt, tmp_path, source_binding=binding)


def test_reviewed_bound_three_pass_evidence_only_qualifies_controlled_experiment(tmp_path):
    receipt, binding, q, reports = qualification_fixture(tmp_path)
    seal_qualification(tmp_path, q, reports)
    export.validate_reference_lk_receipt(
        receipt,
        tmp_path,
        source_capture_sha256=binding["source_manifest_sha256"],
        source_index_sha256=binding["reconstruction_input_sha256"],
        geometry_sha256=binding["geometry_sha256"],
        model_sha256=binding["model_sha256"],
    )
    result = export.validate_reference_lk_qualification(receipt, tmp_path, source_binding=binding)
    assert result["controlled_test_qualified"] is True
    assert (
        result["scope"] == "controlled_experimental_test_only"
        and result["execution_qualified"] is False
    )


def test_89_unknown_negatives_with_unattempted_gap_frames_cannot_qualify(tmp_path):
    receipt, binding, q, reports = qualification_fixture(tmp_path)
    original = reports["negative"]["sample_rows"][0]
    reports["negative"]["sample_rows"] = [
        dict(
            original,
            source_index=index,
            diagnostic=dict(method="measured_reference_lk" if index < 9 else "not_attempted"),
        )
        for index in range(89)
    ]
    reports["negative"].update(sample_count=89, counts=dict(unknown=89))
    seal_qualification(tmp_path, q, reports)
    with pytest.raises(ValueError, match="qualification_invalid"):
        export.validate_reference_lk_qualification(receipt, tmp_path, source_binding=binding)

    # Identical all-unknown facts are eligible for explicit review only after
    # each image actually reached the real measured localization path.
    for row in reports["negative"]["sample_rows"]:
        row["diagnostic"] = dict(method="measured_reference_lk")
    seal_qualification(tmp_path, q, reports)
    assert (
        export.validate_reference_lk_qualification(receipt, tmp_path, source_binding=binding)[
            "controlled_test_qualified"
        ]
        is True
    )
