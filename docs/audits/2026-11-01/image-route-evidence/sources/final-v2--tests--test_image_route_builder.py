"""Small injected decoder fixtures exercise publication, not localization truth."""

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import image_route_builder as builder
from scripts.pilot.image_route_review import read_image_route_review


def digest(value):
    return hashlib.sha256(value).hexdigest()


def snapshot(folder):
    return {
        str(p.relative_to(folder)): digest(p.read_bytes()) for p in folder.rglob("*") if p.is_file()
    }


@pytest.fixture
def source(tmp_path, monkeypatch):
    job = tmp_path / "job"
    folder = job / "input"
    folder.mkdir(parents=True)
    frames = [dict(index=i, relative_ticks_90k=i * 27000, sha256=f"{i:064x}") for i in range(12)]
    raw = dict(
        video_h264=b"not-decoded-by-unit-fixture",
        frames_jsonl=b"".join((json.dumps(r) + "\n").encode() for r in frames),
        inputs_jsonl=b"{}\n",
    )
    manifest = dict(
        schema="sphere-browser-teaching-v2",
        files={
            name.replace("_", "."): dict(bytes=len(value), sha256=digest(value))
            for name, value in raw.items()
        },
        config=dict(width=64, height=48, profile={}),
    )
    manifest["files"]["video.h264"] = dict(
        bytes=len(raw["video_h264"]), integrity="sha256_per_access_unit_in_frames_jsonl"
    )
    originals = {name.replace("_", "."): value for name, value in raw.items()}
    originals["manifest.json"] = json.dumps(manifest).encode()
    originals["COMPLETE"] = json.dumps(
        dict(manifest_sha256=digest(originals["manifest.json"]))
    ).encode()
    for name, value in originals.items():
        (folder / name).write_bytes(value)
    capture = SimpleNamespace(
        manifest=manifest,
        frames=tuple(frames),
        geometry=(64, 48),
        originals={k: v for k, v in originals.items() if k != "video.h264"},
    )
    (job / "state.json").write_text('{"phase":"failed"}')
    (job / "geometry.json").write_text('{"existing_geometry":true}')
    monkeypatch.setattr(builder, "validate_browser", lambda _: capture)

    def decode(cap):
        for row in cap.frames:
            pixels = np.full((48, 64, 3), row["index"] + 10, np.uint8)
            yield row, SimpleNamespace(to_ndarray=lambda *, format, image=pixels: image)

    monkeypatch.setattr(builder, "decoded_browser", decode)

    def features(gray, mask, cv, numpy):
        # The fake descriptor stage makes orchestration cheap. Verification
        # below is explicitly injected and conveys no real-image success claim.
        points = np.array([[1.0, 10.0], [2.0, 20.0]], np.float32)
        descriptors = np.full((2, 128), 0.1, np.float32)
        coarse = np.zeros(191, np.float32)
        coarse[0] = float(gray[0, 0]) / 255
        return points, descriptors, coarse

    monkeypatch.setattr(builder, "_features", features)
    monkeypatch.setattr(builder, "_verify", lambda *args: 0.9)
    monkeypatch.setattr(
        builder,
        "_measure",
        lambda _: dict(
            system="Windows",
            availableRamBytes=4 * builder.GIB,
            freeDiskBytes=builder.GIB,
            committedBytes=5 * builder.GIB,
            commitLimitBytes=10 * builder.GIB,
        ),
    )
    return job, capture


def build(job, **kwargs):
    return builder.run(job, "none", limits=builder.Limits(references=4, queries=6), **kwargs)


def assert_no_partial(job):
    assert not (job / "image-route-review").exists()
    assert not list(job.glob(".image-route-review-building-*"))
    assert not (job / ".image-route-review-builder.lock").exists()


def test_publishes_atomic_source_bound_review_and_reusable_index(source):
    job, capture = source
    before = snapshot(job)
    events = []

    def progress(event):
        assert not (job / "image-route-review").exists()
        assert 0 <= event["cache_bytes"] <= builder.MAX_CACHE_BYTES
        events.append(event)

    outcome = build(job, progress=progress)
    assert outcome["phase"] == "ready" and outcome["reused"] is False
    data = json.loads(read_image_route_review(job))
    assert len(data["reference_ticks_90k"]) == 4 and len(data["samples"]) == 6
    assert all(
        data[key] is False
        for key in ("position_confirmed", "arrival_confirmed", "execution_qualified")
    )
    assert not {s["ticks_90k"] for s in data["samples"]} & set(data["reference_ticks_90k"])
    assert {name: digest((job / name).read_bytes()) for name in before} == before
    metadata, index = builder.read_index(job)
    assert len(index) == 4 and metadata["source_unchanged"] is True
    assert metadata["minimap_fusion"] is False
    assert metadata["selection"] == "uniform_source_pts_no_sfm"
    assert metadata["received_clock"] == "synthetic_zero_latency_query_pts"
    assert metadata["mask_mode"] == "none" and metadata["exclusions"] == []
    assert events[-1]["completed"] == events[-1]["total"] == 6
    sealed = snapshot(job)
    assert build(job)["reused"] is True
    assert snapshot(job) == sealed


def test_existing_manual_review_is_reused_and_never_overwritten(source):
    job, _ = source
    build(job)
    (job / "image-route-review/producer.json").unlink()
    before = snapshot(job)
    result = build(job)
    assert result["reused"] is True and result["index_available"] is False
    assert snapshot(job) == before


def test_invalid_existing_review_is_not_repaired_or_truncated(source):
    job, _ = source
    folder = job / "image-route-review"
    folder.mkdir()
    (folder / "review.json").write_bytes(b"foreign-artifact")
    before = snapshot(job)
    with pytest.raises((ValueError, FileNotFoundError)):
        build(job)
    assert snapshot(job) == before


def test_source_changed_between_passes_cannot_publish(source):
    job, _ = source

    def progress(event):
        if event["phase"] == "reference_index":
            (job / "input/video.h264").write_bytes(b"changed-source")

    with pytest.raises(ValueError, match="source_changed"):
        build(job, progress=progress)
    assert_no_partial(job)
    assert json.loads((job / "geometry.json").read_text()) == {"existing_geometry": True}


def test_wrong_present_video_digest_refused_before_output(source):
    job, capture = source
    capture.manifest["files"]["video.h264"]["sha256"] = "0" * 64
    raw = json.dumps(capture.manifest).encode()
    capture.originals["manifest.json"] = raw
    (job / "input/manifest.json").write_bytes(raw)
    marker = json.dumps(dict(manifest_sha256=digest(raw))).encode()
    capture.originals["COMPLETE"] = marker
    (job / "input/COMPLETE").write_bytes(marker)
    with pytest.raises(ValueError, match="video_binding"):
        build(job)
    assert_no_partial(job)


def test_changed_source_or_corrupt_index_cannot_be_reused(source):
    job, _ = source
    build(job)
    video = job / "input/video.h264"
    old = video.read_bytes()
    video.write_bytes(b"X" * len(old))
    with pytest.raises(ValueError, match="source_changed"):
        build(job)
    video.write_bytes(old)
    cache = next((job / "image-route-review/index").glob("*.npz"))
    cache.write_bytes(b"broken")
    before = snapshot(job)
    with pytest.raises(ValueError, match="index_cache"):
        build(job)
    assert snapshot(job) == before


@pytest.mark.parametrize("cancel_path", ["CANCEL", "image-route-workspace/CANCEL"])
def test_cancellation_cleans_only_owned_stage_and_preserves_source(source, cancel_path):
    job, _ = source
    original = snapshot(job)

    def progress(event):
        target = job / cancel_path
        target.parent.mkdir(exist_ok=True)
        target.touch()

    with pytest.raises(RuntimeError, match="cancelled"):
        build(job, progress=progress)
    assert_no_partial(job)
    assert {name: digest((job / name).read_bytes()) for name in original} == original


def test_cache_quota_fails_without_partial_publication(source):
    job, _ = source
    with pytest.raises(RuntimeError, match="cache_quota"):
        builder.run(job, "none", limits=builder.Limits(references=4, queries=6, cache_bytes=1))
    assert_no_partial(job)


def test_deadline_is_enforced_after_reference_pass(source, monkeypatch):
    job, _ = source
    clock = [0.0]
    monkeypatch.setattr(builder.time, "monotonic", lambda: clock[0])
    with pytest.raises(RuntimeError, match="timeout"):
        builder.run(
            job,
            "none",
            limits=builder.Limits(references=4, queries=6, seconds=1.0),
            progress=lambda event: clock.__setitem__(0, 2.0),
        )
    assert_no_partial(job)


def test_runtime_resource_drop_does_not_publish(source, monkeypatch):
    job, _ = source
    healthy = builder._measure(job)

    def progress(event):
        monkeypatch.setattr(
            builder,
            "_measure",
            lambda _: {**healthy, "availableRamBytes": builder.RUNTIME_RAM_BYTES - 1},
        )

    with pytest.raises(RuntimeError, match="resource_guard"):
        build(job, progress=progress)
    assert_no_partial(job)


def test_rename_failure_leaves_no_visible_partial_result(source, monkeypatch):
    job, _ = source

    def failed_rename(*args):
        raise PermissionError("sharing violation")

    monkeypatch.setattr(Path, "rename", failed_rename)
    with pytest.raises(PermissionError):
        build(job)
    assert_no_partial(job)


def test_exact_rgb_references_cannot_confirm_queries(source, monkeypatch):
    job, capture = source
    pixels = np.full((48, 64, 3), 10, np.uint8)
    monkeypatch.setattr(
        builder,
        "decoded_browser",
        lambda cap: iter(
            (row, SimpleNamespace(to_ndarray=lambda **_: pixels)) for row in cap.frames
        ),
    )
    build(job)
    data = json.loads(read_image_route_review(job))
    assert all(
        r["raw_reference_ticks_90k"] is None and r["sequence_reference_ticks_90k"] is None
        for r in data["samples"]
    )
    producer = json.loads((job / "image-route-review/producer.json").read_bytes())
    assert all(r["exact_reference_repeat"] and r["checked"] == 0 for r in producer["queries"])


def test_nearby_references_are_unchecked_not_failed_matches(source):
    job, capture = source
    for row in capture.frames:
        row["relative_ticks_90k"] = row["index"] * 900
    # Keep the source frame index/manifest genuinely bound to the fixture clock.
    raw = b"".join((json.dumps(row) + "\n").encode() for row in capture.frames)
    (job / "input/frames.jsonl").write_bytes(raw)
    capture.originals["frames.jsonl"] = raw
    manifest = capture.manifest
    manifest["files"]["frames.jsonl"] = dict(bytes=len(raw), sha256=digest(raw))
    raw = json.dumps(manifest).encode()
    (job / "input/manifest.json").write_bytes(raw)
    capture.originals["manifest.json"] = raw
    marker = json.dumps(dict(manifest_sha256=digest(raw))).encode()
    (job / "input/COMPLETE").write_bytes(marker)
    capture.originals["COMPLETE"] = marker
    build(job)
    with np.load(job / "image-route-review/evidence.npz", allow_pickle=False) as evidence:
        assert not evidence["checked"].any() and not evidence["scores"].any()


def test_uniform_pts_plan_uses_all_capture_extent_without_handpicked_indices():
    rows = tuple(
        dict(index=i, relative_ticks_90k=t)
        for i, t in enumerate((0, 1, 2, 3, 9000, 18000, 90000, 180000, 270000))
    )
    capture = SimpleNamespace(frames=rows)
    references, queries = builder.frame_plan(capture, builder.Limits(references=4, queries=3))
    assert references[0] == rows[0] and references[-1] == rows[-1]
    assert len(references) == 4 and len(queries) == 3
    assert not {r["index"] for r in references} & {r["index"] for r in queries}
    assert [r["index"] for r in queries] == sorted({r["index"] for r in queries})
    with pytest.raises(ValueError, match="duration"):
        builder.frame_plan(
            SimpleNamespace(frames=rows[:-1] + (dict(index=8, relative_ticks_90k=602 * 90000),)),
            builder.Limits(),
        )


def test_native_guard_has_separate_ram_commit_and_disk_budgets():
    base = dict(
        system="Windows",
        availableRamBytes=3 * builder.GIB,
        freeDiskBytes=384 * builder.MIB,
        committedBytes=5 * builder.GIB,
        commitLimitBytes=10 * builder.GIB,
    )
    assert builder.resource_findings(base, admission=True) == []
    assert "ram_reserve" in builder.resource_findings(
        {**base, "availableRamBytes": 3 * builder.GIB - 1}, admission=True
    )
    assert "commit_reserve" in builder.resource_findings(
        {**base, "committedBytes": 8 * builder.GIB}, admission=True
    )
    assert "commit_reserve" in builder.resource_findings(
        {**base, "committedBytes": 91 * builder.GIB, "commitLimitBytes": 100 * builder.GIB},
        admission=False,
    )
    assert "commit_unknown" in builder.resource_findings(
        {**base, "commitLimitBytes": None}, admission=False
    )
    assert "disk_reserve" in builder.resource_findings(
        {**base, "freeDiskBytes": 383 * builder.MIB}, admission=True
    )
    assert (
        builder.resource_findings(
            {**base, "freeDiskBytes": 256 * builder.MIB},
            admission=False,
            cache_bytes=builder.MAX_CACHE_BYTES,
        )
        == []
    )


def test_index_header_is_bounded_before_array_allocation(tmp_path):
    cache = tmp_path / "bad.npz"
    with zipfile.ZipFile(cache, "w") as archive:
        for name, shape in [
            ("points.npy", (10**9, 2)),
            ("descriptors.npy", (0, 128)),
            ("coarse.npy", (191,)),
        ]:
            stream = io.BytesIO()
            np.lib.format.write_array_header_1_0(
                stream, dict(shape=shape, fortran_order=False, descr="<f4")
            )
            archive.writestr(name, stream.getvalue())
    with pytest.raises(ValueError, match="array_header"):
        builder._checked_npz(cache, np)


def test_actual_fundamental_verification_requires_independent_spread_correspondences():
    import cv2

    rng = np.random.default_rng(819)
    count = 100
    xyz = rng.uniform([-3.0, -1.8, 5.0], [3.0, 1.8, 12.0], (count, 3))
    target = xyz + [0.7, 0.1, 0.2]
    calibration = np.array([[650.0, 0.0, 480.0], [0.0, 650.0, 270.0], [0.0, 0.0, 1.0]])

    def project(points):
        pixels = points @ calibration.T
        return (pixels[:, :2] / pixels[:, 2:]).astype(np.float32)

    a, b = project(xyz), project(target)
    descriptors = rng.random((count, 128)).astype(np.float32)
    coarse = np.zeros(191, np.float32)
    assert (
        builder._verify((a, descriptors, coarse), (b, descriptors, coarse), (540, 960), cv2, np)
        > 0.9
    )
    shuffled = rng.permutation(b)
    assert (
        builder._verify(
            (a, descriptors, coarse), (shuffled, descriptors, coarse), (540, 960), cv2, np
        )
        == 0.0
    )
    # Multiple SIFT orientations at four pixel locations are not100 independent
    # scene observations, even with perfect one-to-one descriptor identities.
    duplicate_a = np.tile(a[:4], (25, 1))
    duplicate_b = np.tile(b[:4], (25, 1))
    assert (
        builder._verify(
            (duplicate_a, descriptors, coarse),
            (duplicate_b, descriptors, coarse),
            (540, 960),
            cv2,
            np,
        )
        == 0.0
    )


@pytest.fixture
def codec_job(tmp_path, monkeypatch):
    pytest.importorskip("av")
    # Reuse the established real codec/release-journal fixture, not an invented
    # video-manifest shape. Its video entry deliberately has no aggregate SHA.
    from tests.test_motor_browser_teach import BrowserTeachTests

    fixture = BrowserTeachTests()
    fixture.setUp()
    try:
        job = tmp_path / "real-job"
        job.mkdir()
        shutil.copytree(fixture.source, job / "input")
        manifest = json.loads((job / "input/manifest.json").read_bytes())
        manifest["files"]["video.h264"]["integrity"] = "sha256_per_access_unit_in_frames_jsonl"
        raw = json.dumps(manifest).encode()
        (job / "input/manifest.json").write_bytes(raw)
        (job / "input/COMPLETE").write_text(json.dumps(dict(manifest_sha256=digest(raw))))
        monkeypatch.setattr(
            builder,
            "_measure",
            lambda _: dict(
                system="Windows",
                availableRamBytes=4 * builder.GIB,
                freeDiskBytes=builder.GIB,
                committedBytes=5 * builder.GIB,
                commitLimitBytes=10 * builder.GIB,
            ),
        )
        yield job
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize("schema", ["sphere-browser-teaching-v1", "sphere-browser-teaching-v2"])
def test_real_per_access_unit_capture_builds_with_two_complete_decodes(
    codec_job, monkeypatch, schema
):
    job = codec_job
    manifest = json.loads((job / "input/manifest.json").read_bytes())
    assert "sha256" not in manifest["files"]["video.h264"]
    manifest["schema"] = schema
    raw = json.dumps(manifest).encode()
    (job / "input/manifest.json").write_bytes(raw)
    (job / "input/COMPLETE").write_text(json.dumps(dict(manifest_sha256=digest(raw))))
    before = snapshot(job / "input")
    decoder = builder.decoded_browser
    completed = []

    def tracked(capture):
        count = 0
        for row, frame in decoder(capture):
            count += 1
            yield row, frame
        completed.append(count)

    monkeypatch.setattr(builder, "decoded_browser", tracked)
    result = build(job)
    assert result["phase"] == "ready" and completed == [16, 16]
    assert snapshot(job / "input") == before
    metadata, _ = builder.read_index(job)
    assert metadata["source_hashes"]["video.h264"] == before["video.h264"]
    assert metadata["source_video_binding"] == "per_access_unit_decode_and_computed_aggregate"


@pytest.mark.parametrize("pass_number", [1, 2])
def test_real_bad_access_unit_fails_either_decode_without_publication(codec_job, pass_number):
    job = codec_job

    def tamper():
        path = job / "input/video.h264"
        raw = bytearray(path.read_bytes())
        raw[20] ^= 1
        path.write_bytes(raw)

    if pass_number == 1:
        tamper()

    def progress(event):
        if pass_number == 2 and event["phase"] == "reference_index":
            tamper()

    with pytest.raises(ValueError, match="access_unit_hash"):
        build(job, progress=progress)
    assert_no_partial(job)


@pytest.mark.parametrize(
    "options",
    [
        dict(references=257),
        dict(queries=1025),
        dict(cache_bytes=builder.MAX_CACHE_BYTES + 1),
        dict(seconds=181),
        dict(seconds=float("nan")),
    ],
)
def test_invalid_limits_are_not_admitted(options):
    with pytest.raises(ValueError, match="limits"):
        builder.Limits(**options)
