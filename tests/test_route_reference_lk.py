import hashlib
import json
import subprocess
import sys
import uuid
from dataclasses import asdict

import numpy as np
import pytest

from motor_worker import route_reference_lk as lk
from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import RouteLocalizer, feature_mask, pipeline_id


def test_legacy_controller_import_does_not_require_new_family_exporter_source():
    script = """
from pathlib import Path
original = Path.read_bytes
def without_exporter(path):
    if path.name == 'route_reference_lk_export.py':
        raise FileNotFoundError('exporter not in worker package')
    return original(path)
Path.read_bytes = without_exporter
from motor_worker.walk_route import WalkRouteFollower
from motor_worker.vehicle_route import VehicleRouteFollower
from motor_worker.route_reference_lk import reference_lk_pipeline_id
try:
    reference_lk_pipeline_id()
except FileNotFoundError:
    pass
else:
    raise AssertionError('new family must still require its exporter fingerprint')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(folder, *, change=None):
    folder.mkdir(parents=True, exist_ok=True)
    profile = RouteViewProfile(
        str(uuid.uuid4()), 960, 540, (0.0, 0.0, 1.0, 1.0), ((0.0, 0.975, 1.0, 1.0),)
    )
    count, views = 40, 3
    xy = np.array([(120 + x * 80, 100 + y * 75) for y in range(4) for x in range(10)], np.float32)
    z = np.linspace(5.0, 9.0, count)
    xyz = np.c_[(xy[:, 0] - 480) / 500 * z, (xy[:, 1] - 270) / 500 * z, z]
    arrays = dict(
        grays=np.full((views, 540, 960), 127, np.uint8),
        mask=feature_mask(profile),
        offsets=np.arange(0, (views + 1) * count, count, dtype="<u4"),
        native_ids=np.tile(np.arange(count, dtype="<u8"), views),
        native_rows=np.tile(np.arange(count, dtype="<u4"), views),
        pixels=np.tile(xy, (views, 1)).astype("<f4"),
        xyz=np.tile(xyz, (views, 1)).astype("<f8"),
    )
    model_sha = {
        name: "a" * 64
        for name in ("cameras.bin", "images.bin", "points3D.bin", "frames.bin", "rigs.bin")
    }
    source_identity = dict(
        source_capture_sha256="b" * 64,
        source_index_sha256="c" * 64,
        source_geometry_sha256="d" * 64,
        model_sha256=model_sha,
    )
    data = dict(
        schema=lk.SCHEMA,
        id=str(uuid.uuid4()),
        world_revision=str(uuid.uuid4()),
        source_sha256=lk.canonical_hash(source_identity),
        pipeline_sha256=lk.reference_lk_pipeline_id(),
        profile=asdict(profile),
        intrinsics=[500.0, 500.0, 480.0, 270.0],
        camera_trace=[[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]],
        source_seconds=[0.0, 0.3, 0.6],
        reference_rgb_sha256=[str(i + 1) * 64 for i in range(views)],
        source_frame_indices=[0, 10, 20],
        **{k: v for k, v in source_identity.items() if k != "model_sha256"},
        model_sha256=sorted(model_sha.items()),
        reference_names=[f"{i:08}.png" for i in range(views)],
        source_png_sha256=["e" * 64] * views,
        reference_gray_sha256=[
            hashlib.sha256(gray.tobytes()).hexdigest() for gray in arrays["grays"]
        ],
        native_row_counts=[count] * views,
        cache_file=lk.CACHE_FILE,
        observations=count * views,
        execution_qualified=False,
    )
    if change:
        change(data, arrays)
    cache = folder / lk.CACHE_FILE
    with cache.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    data["cache_sha256"] = digest(cache)
    path = folder / "route.json"
    path.write_text(json.dumps(data), encoding="utf8")
    return path, data


def loaded(tmp_path):
    path, data = artifact(tmp_path)
    return lk.ReferenceLKRoute.load(path, sha256=digest(path)), path, data


def test_genuine_family_has_no_descriptor_placeholders_and_legacy_fingerprint_is_unchanged(
    tmp_path,
):
    before = pipeline_id()
    route, _, _ = loaded(tmp_path)
    try:
        assert not hasattr(route, "descriptors")
        assert lk.reference_lk_pipeline_id() != before
        assert pipeline_id() == before
        support = lk.reference_lk_support(route)
        assert support["all_reference_neighborhoods_supported"]
        assert support["views_below_24"] == 0
    finally:
        route.close()


def test_cache_is_shared_immutable_and_released_only_after_last_owner(tmp_path):
    route, path, _ = loaded(tmp_path)
    second = lk.ReferenceLKRoute.load(path, sha256=digest(path))
    lease = route.acquire_cache()
    try:
        assert route._lease.entry is second._lease.entry
        assert route._lease.arrays["grays"] is lease.arrays["grays"]
        with pytest.raises(ValueError):
            lease.arrays["grays"].setflags(write=True)
        route.close()
        assert second._lease.arrays["grays"].shape == (3, 540, 960)
        second.close()
        assert lease.arrays["grays"].shape == (3, 540, 960)
    finally:
        lease.close()
        route.close()
        second.close()
    assert not any(key[0] == str((tmp_path / lk.CACHE_FILE).resolve()) for key in lk._CACHES)


@pytest.mark.parametrize(
    "kind", ["pixels", "rows", "ids", "xyz", "mask", "gray", "offsets", "source", "family"]
)
def test_invalid_measured_native_rows_profiles_or_source_are_rejected_and_not_cached(
    tmp_path, kind
):
    def change(data, arrays):
        if kind == "pixels":
            arrays["pixels"][0] = [-1.0, 100.0]
        if kind == "rows":
            arrays["native_rows"][0] = 999
        if kind == "ids":
            arrays["native_ids"][0] = arrays["native_ids"][1]
        if kind == "xyz":
            arrays["xyz"][40, 0] += 0.1
        if kind == "mask":
            arrays["mask"][:] = 255
        if kind == "gray":
            arrays["grays"][0, 0, 0] ^= 1
        if kind == "offsets":
            arrays["offsets"][1] = 1
        if kind == "source":
            data["source_sha256"] = "f" * 64
        if kind == "family":
            data["pipeline_sha256"] = pipeline_id()

    path, _ = artifact(tmp_path, change=change)
    with pytest.raises(ProtocolError):
        lk.ReferenceLKRoute.load(path, sha256=digest(path))
    assert not any(key[0] == str((tmp_path / lk.CACHE_FILE).resolve()) for key in lk._CACHES)


@pytest.mark.parametrize("kind", ["extra_entry", "object", "shape", "dtype"])
def test_cache_headers_are_checked_before_loading_unbounded_or_pickle_payloads(tmp_path, kind):
    def change(_data, arrays):
        if kind == "extra_entry":
            arrays["unexpected"] = np.array([1])
        if kind == "object":
            arrays["xyz"] = np.array([object()], object)
        if kind == "shape":
            arrays["grays"] = np.zeros((1, 1, 1), np.uint8)
        if kind == "dtype":
            arrays["grays"] = arrays["grays"].astype(np.float64)

    path, _ = artifact(tmp_path, change=change)
    with pytest.raises(ProtocolError):
        lk.ReferenceLKRoute.load(path, sha256=digest(path))


def test_source_switch_cannot_reuse_cache_after_asset_bytes_changed(tmp_path):
    route, path, _ = loaded(tmp_path)
    try:
        with (tmp_path / lk.CACHE_FILE).open("ab") as stream:
            stream.write(b"changed")
        with pytest.raises(ProtocolError, match="cache_integrity"):
            lk.ReferenceLKRoute.load(path, sha256=digest(path))
    finally:
        route.close()


def test_new_constructor_reuses_exact_pnp_freshness_motion_and_image_gates(tmp_path, monkeypatch):
    route, _, _ = loaded(tmp_path)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    tracker = lk.ReferenceLKLocalizer(
        route, capture_epoch=ids[0], episode_id=ids[1], goal_revision=ids[2], clock=lambda: 1.0
    )
    try:
        for name in (
            "observe",
            "_verify_correspondences",
            "_fresh",
            "_rank_proposals",
            "_motion_limit",
            "_nearest",
            "_project",
        ):
            assert getattr(lk.ReferenceLKLocalizer, name) is getattr(RouteLocalizer, name)
        np.testing.assert_array_equal(
            tracker.lengths, np.linalg.norm(np.diff(route.camera_trace, axis=0), axis=1)
        )
        monkeypatch.setattr(
            tracker,
            "_features",
            lambda frame: pytest.fail("stale frames must be rejected before extraction"),
        )
        frame = PolicyFrame(ids[0], 1, 0.0, 960, 540, bytes(960 * 540 * 3))
        pose = tracker.observe(frame, episode_id=ids[1], goal_revision=ids[2], scene="active")
        assert pose.state == "unknown" and pose.center is None
    finally:
        tracker.close()
        route.close()


def test_invalid_lk_matches_cannot_bypass_pnp_and_closed_tracker_cannot_observe(
    tmp_path, monkeypatch
):
    route, _, _ = loaded(tmp_path)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    tracker = lk.ReferenceLKLocalizer(
        route, capture_epoch=ids[0], episode_id=ids[1], goal_revision=ids[2], clock=lambda: 1.0
    )
    try:
        monkeypatch.setattr(
            tracker.cv, "calcOpticalFlowPyrLK", lambda *args, **kwargs: (None, None, None)
        )
        monkeypatch.setattr(
            tracker,
            "_verify_correspondences",
            lambda *args: pytest.fail("no measured LK correspondence must reach PnP"),
        )
        frame = PolicyFrame(ids[0], 1, 1.0, 960, 540, bytes(960 * 540 * 3))
        pose = tracker.observe(frame, episode_id=ids[1], goal_revision=ids[2], scene="active")
        assert pose.state == "unknown" and pose.center is None
        tracker.close()
        pose = tracker.observe(
            PolicyFrame(ids[0], 2, 1.0, 960, 540, bytes(960 * 540 * 3)),
            episode_id=ids[1],
            goal_revision=ids[2],
            scene="active",
        )
        assert pose.state == "unknown" and pose.center is None
    finally:
        tracker.close()
        route.close()
