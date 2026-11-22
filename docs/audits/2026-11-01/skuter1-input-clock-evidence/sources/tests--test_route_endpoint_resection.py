import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.pilot.route_endpoint_resection import (
    _colmap_to_cv,
    _cv_to_colmap,
    _fit_pose,
    _inside,
    _split,
    repair_endpoints,
)


def camera():
    p = pytest.importorskip("pycolmap")
    return p.Camera(
        model="SIMPLE_PINHOLE", width=960, height=540, params=np.array([500.0, 480.0, 270.0])
    )


def calibrated_tracks():
    cam = camera()
    ids = np.arange(1, 121, dtype=np.uint64)
    xy = np.array([(70 + (i % 12) * 72, 55 + (i // 12) * 46) for i in range(120)], dtype=float)
    z = 5 + (ids % 7) * 0.17
    xyz = np.column_stack(((xy[:, 0] - 480) * z / 500, (xy[:, 1] - 270) * z / 500, z))
    return cam, ids, xy, xyz


def test_calibrated_pose_accepts_separately_held_out_landmarks():
    cam, ids, xy, xyz = calibrated_tracks()
    pose, report = _fit_pose(ids, xy, xyz, cam, 960, 540)
    assert pose is not None and report["accepted"]
    assert report["train_inliers"] >= 30 and report["heldout_le4"] >= 15
    assert report["heldout_cells"] >= 4


def test_heldout_corruption_cannot_pass_on_train_only():
    cam, ids, xy, xyz = calibrated_tracks()
    xy = xy.copy()
    xy[[not _split(i) for i in ids]] += [80, 60]
    pose, report = _fit_pose(ids, xy, xyz, cam, 960, 540)
    assert pose is None and not report["accepted"] and report["heldout_le4"] < 15


def test_mask_and_half_pixel_convention():
    assert _inside(20, 30, 100, 100, ((0, 0, 0.1, 0.5),))
    assert not _inside(5, 30, 100, 100, ((0, 0, 0.1, 0.5),))
    assert not _inside(100, 30, 100, 100, ())
    original = np.array([[5.5, 10.5], [100.5, 25.5]])
    assert np.array_equal(_colmap_to_cv(original), [[5.0, 10.0], [100.0, 25.0]])
    assert np.array_equal(_cv_to_colmap(_colmap_to_cv(original)), original)


class EmptyRec:
    images = {}

    def reg_image_ids(self):
        return []

    def num_points3D(self):
        return 0


def make_minimal(tmp_path, *, matching=True):
    job, prepared = tmp_path / "job", tmp_path / "job/prepared"
    (job / "input").mkdir(parents=True)
    prepared.mkdir()
    manifest = b'{"config":{}}'
    (job / "input/manifest.json").write_bytes(manifest)
    (job / "input/video.h264").write_bytes(b"ab")
    frames = [
        {
            "index": i,
            "relative_ticks_90k": i * 90000,
            "sha256": hashlib.sha256(bytes([97 + i])).hexdigest(),
        }
        for i in range(2)
    ]
    (job / "input/frames.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in frames), encoding="utf8"
    )
    sha = hashlib.sha256(manifest).hexdigest() if matching else "0" * 64
    data = {
        "source_manifest_sha256": sha,
        "images": [
            {
                "image": "images/one.png",
                "source_index": 0,
                "relative_ticks_90k": 0,
                "png_sha256": "1" * 64,
                "source_access_unit_sha256": frames[0]["sha256"],
            },
            {
                "image": "images/two.png",
                "source_index": 1,
                "relative_ticks_90k": 90000,
                "png_sha256": "2" * 64,
                "source_access_unit_sha256": frames[1]["sha256"],
            },
        ],
    }
    (prepared / "reconstruction-input.json").write_text(json.dumps(data), encoding="utf8")
    return job, prepared


@pytest.mark.parametrize(
    ("matching", "reason"), [(True, "no_anchor"), (False, "manifest_hash_mismatch")]
)
def test_no_anchor_or_bad_hash_keeps_baseline_and_files(tmp_path, matching, reason):
    pytest.importorskip("pycolmap")
    job, prepared = make_minimal(tmp_path, matching=matching)
    before = {str(p): p.read_bytes() for p in job.rglob("*") if p.is_file()}
    baseline = EmptyRec()
    chosen, report = repair_endpoints(
        job, prepared, baseline, 2, 0.0, 1.0, lambda: None, lambda *x: None
    )
    assert chosen is baseline and report["reason"] == reason and not report["accepted"]
    assert before == {str(p): p.read_bytes() for p in job.rglob("*") if p.is_file()}


def test_cancellation_propagates_without_writing(tmp_path):
    pytest.importorskip("pycolmap")
    job, prepared = make_minimal(tmp_path)

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        repair_endpoints(job, prepared, EmptyRec(), 2, 0.0, 1.0, cancel, lambda *x: None)
    assert not (prepared / "endpoint-resection").exists()


@pytest.mark.parametrize(
    "case",
    ["missing_manifest", "invalid_json", "duplicate_index", "duplicate_tick", "duplicate_frame"],
)
def test_bad_provenance_is_rejected_before_any_workspace_write(tmp_path, case):
    pytest.importorskip("pycolmap")
    job, prepared = make_minimal(tmp_path)
    meta = prepared / "reconstruction-input.json"
    if case == "missing_manifest":
        (job / "input/manifest.json").unlink()
    elif case == "invalid_json":
        meta.write_text("{", encoding="utf8")
    elif case in {"duplicate_index", "duplicate_tick"}:
        obj = json.loads(meta.read_text(encoding="utf8"))
        key = "source_index" if case == "duplicate_index" else "relative_ticks_90k"
        obj["images"][1][key] = obj["images"][0][key]
        meta.write_text(json.dumps(obj), encoding="utf8")
    else:
        frames = job / "input/frames.jsonl"
        frames.write_text(frames.read_text(encoding="utf8") * 2, encoding="utf8")
    before = {str(f): f.read_bytes() for f in job.rglob("*") if f.is_file()}
    baseline = EmptyRec()
    chosen, report = repair_endpoints(
        job, prepared, baseline, 2, 0.0, 1.0, lambda: None, lambda *x: None
    )
    assert chosen is baseline and not report["accepted"]
    if case == "duplicate_frame":
        assert report["reason"] == "duplicate_frame_index"
    if case in {"duplicate_index", "duplicate_tick"}:
        assert report["reason"] == "duplicate_image_provenance"
    assert before == {str(f): f.read_bytes() for f in job.rglob("*") if f.is_file()}
    assert not (prepared / "endpoint-resection").exists()


@pytest.mark.parametrize(
    "case", ["accepted", "bad_frame_hash", "bad_access_unit", "quality_rejected", "existing_intent"]
)
def test_real_lk_resection_adds_new_rows_without_mutating_source_or_anchor(
    tmp_path, monkeypatch, case
):
    import sqlite3

    import cv2
    import pycolmap as p

    import scripts.pilot.reconstruct_route as route

    cam, ids, xy, xyz = calibrated_tracks()
    xy = np.array([(35 + (i % 20) * 45, 25 + (i // 20) * 37) for i in range(280)], dtype=float)
    depths = 5 + (np.arange(280) % 7) * 0.17
    xyz = np.column_stack(
        ((xy[:, 0] - 480) * depths / 500, (xy[:, 1] - 270) * depths / 500, depths)
    )
    cam.camera_id = 1
    job, prepared = tmp_path / "job", tmp_path / "job/prepared"
    (job / "input").mkdir(parents=True)
    (prepared / "images").mkdir(parents=True)
    manifest = b'{"config":{}}'
    (job / "input/manifest.json").write_bytes(manifest)
    video = b"frame-zero-frame-one"
    (job / "input/video.h264").write_bytes(video)
    frame_data = [(0, 0, 10, 0, "target.png"), (1, 10, 10, 18000, "anchor.png")]
    rng = np.random.default_rng(17)
    pixels = rng.integers(0, 256, (540, 960), dtype=np.uint8)
    frames, rows = [], []
    for index, offset, size, ticks, name in frame_data:
        path = prepared / "images" / name
        assert cv2.imwrite(str(path), pixels)
        au = hashlib.sha256(video[offset : offset + size]).hexdigest()
        frames.append(
            {
                "index": index,
                "offset": offset,
                "bytes": size,
                "relative_ticks_90k": ticks,
                "sha256": au,
            }
        )
        rows.append(
            {
                "image": "images/" + name,
                "source_index": index,
                "relative_ticks_90k": ticks,
                "source_access_unit_sha256": au,
                "png_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if case == "bad_frame_hash":
        rows[0]["png_sha256"] = "0" * 64
    if case == "bad_access_unit":
        (job / "input/video.h264").write_bytes(b"X" + video[1:])
    (job / "input/frames.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in frames), encoding="utf8"
    )
    (prepared / "reconstruction-input.json").write_text(
        json.dumps(
            {"source_manifest_sha256": hashlib.sha256(manifest).hexdigest(), "images": rows}
        ),
        encoding="utf8",
    )
    with sqlite3.connect(prepared / "database.db") as db:
        db.execute("create table images(image_id integer,name text)")
        db.executemany("insert into images values(?,?)", [(1, "target.png"), (2, "anchor.png")])
    rec = p.Reconstruction()
    rec.add_camera_with_trivial_rig(cam)
    rec.add_image_with_trivial_frame(
        p.Image(name="anchor.png", keypoints=xy, camera_id=1, image_id=2), p.Rigid3d()
    )
    for i, point in enumerate(xyz):
        rec.add_point3D(point, p.Track([p.TrackElement(2, i)]))
    if case == "existing_intent":
        (prepared / "endpoint-resection").mkdir()
        (prepared / "endpoint-resection/intent-marker").write_text("preserve", encoding="utf8")
    before = {str(f): f.read_bytes() for f in job.rglob("*") if f.is_file()}
    monkeypatch.setattr(
        route,
        "model_assessment",
        lambda *a, **kw: (
            None,
            {"scene_admissible": True, "route_admissible": case != "quality_rejected"},
        ),
    )
    chosen, report = repair_endpoints(
        job, prepared, rec, 2, 0.0, 1.0, lambda: None, lambda *x: None
    )
    if case != "accepted":
        assert chosen is rec and not report["accepted"]
        assert (
            report["reason"]
            == {
                "bad_frame_hash": "frame_hash_mismatch",
                "bad_access_unit": "frame_access_unit_hash_mismatch",
                "quality_rejected": "candidate_quality_rejected",
                "existing_intent": "endpoint_resection_existing_intent",
            }[case]
        )
        assert all(Path(name).read_bytes() == body for name, body in before.items())
        assert not (prepared / "endpoint-resection/candidate").exists()
        return
    assert report["accepted"] and chosen.num_reg_images() == 2 and rec.num_reg_images() == 1
    assert report["frames"][0]["heldout_le4"] >= 15
    assert (
        report["invalid_reciprocal"]
        == report["duplicate_image_in_track"]
        == report["nonpositive_depth"]
        == 0
    )
    assert all(Path(name).read_bytes() == body for name, body in before.items())
    assert (prepared / "endpoint-resection/candidate/images.bin").is_file()
