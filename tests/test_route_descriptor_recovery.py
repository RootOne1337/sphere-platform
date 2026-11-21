"""Binding and scheduling regression tests with synthetic current-image correspondences."""

import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from motor_worker import route_descriptor_recovery as recovery
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import RouteLocalizer, SparseRoute, native_reference_pipeline_id
from motor_worker.route_reference_lk import ReferenceLKLocalizer
from scripts.pilot.route_descriptor_attachment import DESCRIPTORS, REVIEW, SCHEMA, load_descriptor_recovery
from scripts.pilot.route_workspace import RouteWorkspaces
from tests.test_route_reference_lk import loaded


@pytest.fixture
def source(tmp_path):
    route, _, _ = loaded(tmp_path)
    try:
        pixels = route._lease.arrays["pixels"][:40].astype(np.float64)
        world = route._lease.arrays["xyz"][:40]
        descriptors = np.eye(len(world), 128, dtype="<f4")
        sidecar = SparseRoute(
            str(uuid.uuid4()), str(uuid.uuid4()), "f" * 64, native_reference_pipeline_id(),
            replace(route.profile, revision=str(uuid.uuid4()), width=1920, height=1080),
            route.intrinsics, tuple(tuple(map(float, p)) for p in world), descriptors.tobytes(),
            route.camera_trace, route.source_seconds, route.reference_rgb_sha256,
            ((0, 1, 2),) * len(world), route.source_capture_sha256, route.source_frame_indices,
        )
        yield route, sidecar, pixels, descriptors
    finally:
        route.close()


def localizer(route, sidecar, now):
    return recovery.ReferenceLKRecoveryLocalizer(
        route, sidecar=sidecar, clock=lambda: now[0],
        capture_epoch=str(uuid.uuid4()), episode_id=str(uuid.uuid4()), goal_revision=str(uuid.uuid4()),
    )


def test_attachment_stays_bound_to_the_reviewed_route_and_descriptor_bytes(source, tmp_path):
    route, sidecar, _, _ = source
    stamp = RouteWorkspaces._runtime_source_stamp
    binding = dict(sha256="a" * 64, cache_sha256=route.cache_sha256, pipeline_sha256=route.pipeline_sha256,
                   geometry_sha256=route.source_geometry_sha256, source_capture_sha256=route.source_capture_sha256,
                   source_index_sha256=route.source_index_sha256, model_sha256=dict(route.model_sha256))
    assert load_descriptor_recovery(tmp_path, binding, stamp=stamp) == (None, (), None)
    descriptor = tmp_path / DESCRIPTORS
    document = dict(schema=SCHEMA, scope="observation_only", reviewed=True,
                    policy=recovery.DESCRIPTOR_RECOVERY_POLICY, binding=binding,
                    runtime_sha256=hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest(),
                    descriptor_sha256=sidecar.save(descriptor),
                    source_proof_sha256="b" * 64, replay_proof_sha256="c" * 64)
    (tmp_path / REVIEW).write_text(json.dumps(document), encoding="utf-8")
    loaded_sidecar, paths, initial_stamp = load_descriptor_recovery(tmp_path, binding, stamp=stamp)
    assert loaded_sidecar == sidecar
    assert initial_stamp == stamp(paths)
    with pytest.raises(ValueError, match="route_descriptor_recovery_review_invalid"):
        load_descriptor_recovery(tmp_path, dict(binding, geometry_sha256="0" * 64), stamp=stamp)
    descriptor.write_text("changed", encoding="utf-8")
    assert stamp(paths) != initial_stamp
    with pytest.raises(ValueError, match="sparse_route_integrity"):
        load_descriptor_recovery(tmp_path, binding, stamp=stamp)


def observe(tracker, now, sequence):
    frame = PolicyFrame(tracker.epoch, sequence, now[0], 960, 540, bytes([sequence]) * (960 * 540 * 3))
    return tracker.observe(frame, episode_id=tracker.episode, goal_revision=tracker.goal, scene="active")


@pytest.mark.parametrize("field", ["source_capture_sha256", "intrinsics", "camera_trace", "source_seconds",
                                  "source_frame_indices", "profile", "pipeline_sha256"])
def test_sidecar_rejects_cross_source_or_incompatible_coordinates(source, field):
    route, sidecar, _, _ = source
    differences = dict(source_capture_sha256="a" * 64, intrinsics=(505.0, *sidecar.intrinsics[1:]),
                       camera_trace=(*sidecar.camera_trace[:-1], (0.21, 0.0, 0.0)),
                       source_seconds=(0.0, 0.3, 0.61), source_frame_indices=(0, 10, 21),
                       profile=replace(sidecar.profile, excluded=((0.0, 0.95, 1.0, 1.0),)),
                       pipeline_sha256="a" * 64)
    with pytest.raises(ProtocolError, match="route_descriptor_recovery_binding"):
        localizer(route, replace(sidecar, **{field: differences[field]}), [10.0])


def test_cold_native_descriptor_pose_uses_the_primary_route_and_original_confirmation(source, monkeypatch):
    route, sidecar, pixels, descriptors = source
    now = [10.0]
    tracker = localizer(route, sidecar, now)
    monkeypatch.setattr(ReferenceLKLocalizer, "_solve", no_lk_geometry)
    monkeypatch.setattr(recovery, "extract_gray_features", lambda gray, mask: (pixels, descriptors))
    try:
        states = []
        for sequence in (1, 2, 3):
            pose = observe(tracker, now, sequence)
            states.append(pose.state)
            assert (pose.route_id, pose.world_revision) == (route.id, route.world_revision)
            assert tracker.last_diagnostic["method"] == "descriptor_pnp"
            assert tracker.last_diagnostic["verifiedCandidateCount"] == 1
            now[0] += 0.1
        assert states == ["confirming", "confirming", "localized"]
        assert tracker.last_diagnostic["motionSourceEnvelopeEligible"] is True
        assert not tracker.xyz.flags.writeable and not tracker.visibility.flags.writeable
    finally:
        tracker.close()


def no_lk_geometry(owner, *args):
    owner.last_diagnostic.update(method="measured_reference_lk", verifiedCandidateCount=0)
    return None


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize(("lk_outcome", "compute", "expected_state", "descriptor_attempt"), [
    ("verified", 0.04, "localized", False),
    ("ambiguous", 0.04, "unknown", False),
    ("empty", 0.04, "localized", True),
    ("empty", 0.12, "unknown", False),
])
def test_lk_first_only_recovers_from_a_timely_geometry_miss(
    source, monkeypatch, warm, lk_outcome, compute, expected_state, descriptor_attempt,
):
    route, sidecar, pixels, descriptors = source
    now, attempts = [10.0], []
    tracker = localizer(route, sidecar, now)

    def features(gray, mask):
        attempts.append(True)
        return pixels, descriptors

    def measured_lk(owner, *args):
        now[0] += compute
        verified = {"verified": 1, "ambiguous": 2, "empty": 0}[lk_outcome]
        owner.last_diagnostic.update(method="measured_reference_lk", verifiedCandidateCount=verified,
                                     candidateReferenceIndices=[2], flowRetainedByCandidate=[0])
        if lk_outcome == "verified":
            return owner._verify_correspondences(owner.xyz, pixels)[:4]
        return None

    monkeypatch.setattr(recovery, "extract_gray_features", features)
    try:
        if warm:
            monkeypatch.setattr(ReferenceLKLocalizer, "_solve", no_lk_geometry)
            for sequence in (1, 2, 3):
                observe(tracker, now, sequence)
                now[0] += 0.1
        monkeypatch.setattr(ReferenceLKLocalizer, "_solve", measured_lk)
        pose = observe(tracker, now, 4)
        if not warm and expected_state == "localized":
            expected_state = "confirming"
        assert pose.state == expected_state
        assert len(attempts) == 3 * int(warm) + int(descriptor_attempt)
        if descriptor_attempt:
            assert tracker.last_diagnostic["method"] == "descriptor_pnp"
            assert "flowRetainedByCandidate" not in tracker.last_diagnostic
    finally:
        tracker.close()


def test_descriptor_extraction_cannot_consume_an_expired_frame(source, monkeypatch):
    route, sidecar, pixels, descriptors = source
    now = [10.0]
    tracker = localizer(route, sidecar, now)
    monkeypatch.setattr(ReferenceLKLocalizer, "_solve", no_lk_geometry)

    def slow_features(gray, mask):
        now[0] += 0.26
        return pixels, descriptors

    def unexpected_matching(*args):
        pytest.fail("descriptor matching started after the current frame expired")

    monkeypatch.setattr(recovery, "extract_gray_features", slow_features)
    monkeypatch.setattr(RouteLocalizer, "_solve", unexpected_matching)
    try:
        pose = observe(tracker, now, 1)
        assert (pose.state, pose.reason) == ("unknown", "route_frame_expired_during_localization")
        assert tracker.confirmations == 0
    finally:
        tracker.close()
