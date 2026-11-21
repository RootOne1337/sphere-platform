"""Bounded, source-bound endpoint resection; never an execution authority.

New 2D rows belong to ENDPOINT_LK, not the original COLMAP feature database.
Run only after all database matching and mapping; do not match this model back
against that database. A failed check leaves the supplied reconstruction intact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import stat
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_masks import capture_exclusions

MAX_VIEWS = 8
MAX_TRACKS = 1024
MAX_SECONDS = 60
MAX_MODEL_POINTS = 100_000
MAX_MODEL_OBSERVATIONS = 1_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _safe_path(root, path, *, file=False, limit=None):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root):
        raise ValueError("endpoint_path_invalid")
    for item in (
        root,
        *(
            root / Path(*path.relative_to(root).parts[:i])
            for i in range(1, len(path.relative_to(root).parts) + 1)
        ),
    ):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("endpoint_path_invalid")
    if file:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or (limit is not None and info.st_size > limit):
            raise ValueError("endpoint_provenance_quota")
    return path


def _preflight(job, prepared, rec, selected, source_start, source_end, bounded):
    job, prepared = Path(job).absolute(), Path(prepared).absolute()
    _safe_path(job, prepared)
    if not prepared.is_dir():
        raise ValueError("endpoint_path_invalid")
    meta = _safe_path(job, prepared / "reconstruction-input.json", file=True, limit=2 * 1024**2)
    manifest_path = _safe_path(job, job / "input/manifest.json", file=True, limit=65536)
    frames_path = _safe_path(job, job / "input/frames.jsonl", file=True, limit=64 * 1024**2)
    _safe_path(job, job / "input/video.h264", file=True, limit=2 * 1024**3)
    provenance = json.loads(meta.read_text("utf8"))
    if not isinstance(provenance, dict):
        raise ValueError("invalid_image_provenance")
    if provenance.get("source_manifest_sha256") != _sha(manifest_path):
        raise ValueError("manifest_hash_mismatch")
    manifest = json.loads(manifest_path.read_text("utf8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    rows = provenance.get("images")
    if (
        type(selected) is not int
        or not isinstance(rows, list)
        or len(rows) != selected
        or not 2 <= selected <= 240
    ):
        raise ValueError("invalid_image_provenance")
    seen_names, seen_indices, seen_ticks = set(), set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_image_provenance")
        image, index, ticks = (
            row.get("image"),
            row.get("source_index"),
            row.get("relative_ticks_90k"),
        )
        if (
            not isinstance(image, str)
            or Path(image).is_absolute()
            or len(Path(image).parts) != 2
            or Path(image).parts[0] != "images"
            or Path(image).name in (".", "..")
            or type(index) is not int
            or index < 0
            or type(ticks) is not int
            or ticks < 0
            or not isinstance(row.get("png_sha256"), str)
            or not _SHA256.fullmatch(row["png_sha256"])
            or not isinstance(row.get("source_access_unit_sha256"), str)
            or not _SHA256.fullmatch(row["source_access_unit_sha256"])
        ):
            raise ValueError("invalid_image_provenance")
        if image in seen_names or index in seen_indices or ticks in seen_ticks:
            raise ValueError("duplicate_image_provenance")
        seen_names.add(image)
        seen_indices.add(index)
        seen_ticks.add(ticks)
    recorded = {}
    with frames_path.open(encoding="utf8") as stream:
        for line in stream:
            bounded()
            frame = json.loads(line)
            if (
                not isinstance(frame, dict)
                or type(frame.get("index")) is not int
                or frame["index"] < 0
            ):
                raise ValueError("invalid_frame_provenance")
            if frame["index"] in recorded:
                raise ValueError("duplicate_frame_index")
            recorded[frame["index"]] = frame
            if len(recorded) > 100_000:
                raise ValueError("endpoint_provenance_quota")
    for row in rows:
        frame = recorded.get(row["source_index"])
        if (
            not frame
            or frame.get("relative_ticks_90k") != row["relative_ticks_90k"]
            or frame.get("sha256") != row["source_access_unit_sha256"]
        ):
            raise ValueError("frame_source_binding")
    if (
        rec.num_points3D() > MAX_MODEL_POINTS
        or len(rec.reg_image_ids()) > 240
        or sum(len(rec.images[i].points2D) for i in rec.reg_image_ids())
        > MAX_MODEL_OBSERVATIONS - MAX_VIEWS * MAX_TRACKS
    ):
        raise ValueError("endpoint_model_quota")
    by_name = {Path(row["image"]).name: row for row in rows}
    registered = {rec.images[i].name: rec.images[i] for i in rec.reg_image_ids()}
    anchors = [
        (by_name[n]["relative_ticks_90k"] / 90000.0, im)
        for n, im in registered.items()
        if n in by_name
    ]
    if not anchors:
        raise ValueError("no_anchor")
    targets = []
    for row in rows:
        name, t = Path(row["image"]).name, row["relative_ticks_90k"] / 90000.0
        if name in registered or min(abs(t - source_start), abs(t - source_end)) > 1.0:
            continue
        anchor_t, anchor = min(anchors, key=lambda item: (abs(item[0] - t), item[0]))
        if abs(anchor_t - t) <= 1.0:
            targets.append((min(abs(t - source_start), abs(t - source_end)), t, row, anchor))
    targets.sort(key=lambda x: (x[0], x[1]))
    if not targets:
        raise ValueError("no_eligible_endpoint")
    db_path = _safe_path(job, prepared / "database.db", file=True, limit=2 * 1024**3)
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        db_rows = db.execute("select name,image_id from images limit 241").fetchall()
    ids = dict(db_rows)
    if len(db_rows) > 240 or len(ids) != len(db_rows) or len(set(ids.values())) != len(ids):
        raise ValueError("endpoint_database_invalid")
    folder = _safe_path(job, prepared / "endpoint-resection")
    if folder.exists():
        raise ValueError("endpoint_resection_existing_intent")
    return manifest, recorded, by_name, targets, ids, folder


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(x, y, width, height, exclusions):
    return (
        0 <= x < width
        and 0 <= y < height
        and not any(
            a * width <= x <= c * width and b * height <= y <= d * height
            for a, b, c, d in exclusions
        )
    )


def _split(point_id):
    return hashlib.sha256(str(int(point_id)).encode("ascii")).digest()[0] < 179


def _colmap_to_cv(xy):
    return xy - 0.5


def _cv_to_colmap(xy):
    return xy + 0.5


def _fit_pose(ids, xy, xyz, camera, width, height):
    import numpy as np
    import pycolmap as p

    train = np.array([_split(i) for i in ids], dtype=bool)
    details = dict(train=int(train.sum()), heldout=int((~train).sum()), accepted=False)
    if train.sum() < 30 or (~train).sum() < 15:
        return None, details
    options = p.AbsolutePoseEstimationOptions()
    options.ransac.max_error = 4.0
    options.ransac.random_seed = 17
    options.ransac.num_threads = 2
    options.ransac.max_num_trials = 2000
    refine = p.AbsolutePoseRefinementOptions()
    refine.refine_focal_length = False
    refine.refine_extra_params = False
    result = p.estimate_and_refine_absolute_pose(xy[train], xyz[train], camera, options, refine)
    if result is None:
        return None, details
    pose = result["cam_from_world"]
    q = xyz[~train] @ pose.rotation.matrix().T + pose.translation
    positive = q[:, 2] > 0
    error = np.linalg.norm(camera.img_from_cam(q) - xy[~train], axis=1)
    valid = positive & np.isfinite(error) & (error <= 4.0)
    cells = np.floor(xy[~train][valid] / [width, height] * 4).astype(int)
    details.update(
        train_inliers=int(result["num_inliers"]),
        heldout_le4=int(valid.sum()),
        heldout_positive=int(positive.sum()),
        heldout_cells=len(set(map(tuple, cells.tolist()))),
    )
    details["accepted"] = (
        details["train_inliers"] >= 30
        and details["heldout_le4"] >= 15
        and details["heldout_cells"] >= 4
    )
    return (pose if details["accepted"] else None), details


def repair_endpoints(
    job,
    prepared,
    rec,
    selected,
    source_start,
    source_end,
    check,
    progress,
    *,
    assessment_check=None,
    mask_mode="game",
):
    job, prepared = Path(job), Path(prepared)
    began = time.monotonic()
    last_check = [0.0]
    caller_failure = [None]

    def bounded():
        now = time.monotonic()
        if now - began > MAX_SECONDS:
            raise TimeoutError("endpoint_resection_timeout")
        if now - last_check[0] >= 0.5:
            try:
                check()  # Caller cancellation and resource failures must propagate.
                if assessment_check is not None:
                    assessment_check()
            except BaseException as error:
                caller_failure[0] = error
                raise
            last_check[0] = now

    bounded()
    result = dict(
        schema="sphere-endpoint-resection-v1",
        accepted=False,
        namespace="ENDPOINT_LK",
        further_original_db_matching=False,
        poses_interpolated=False,
        execution_qualified=False,
        frames=[],
    )
    try:
        import cv2
        import numpy as np
        import pycolmap as p

        from scripts.pilot.reconstruct_route import model_assessment
    except ImportError:
        result["reason"] = "endpoint_native_runtime_unavailable"
        return rec, result
    if not all(
        hasattr(p.Reconstruction, name)
        for name in ("add_image_with_trivial_frame", "add_observation", "write")
    ) or not hasattr(p, "estimate_and_refine_absolute_pose"):
        result["reason"] = "endpoint_native_api_unavailable"
        return rec, result
    if (
        type(source_start) not in (int, float)
        or type(source_end) not in (int, float)
        or not math.isfinite(source_start)
        or not math.isfinite(source_end)
        or not 0 <= source_start < source_end
    ):
        result["reason"] = "invalid_source_time"
        return rec, result
    try:
        manifest, recorded, by_name, targets, ids, folder = _preflight(
            job, prepared, rec, selected, source_start, source_end, bounded
        )
        bounded()
        folder.mkdir()
        (folder / "baseline").mkdir()
        rec.write(folder / "baseline")
        candidate = p.Reconstruction(folder / "baseline")
        cv2.setNumThreads(2)
        cv2.setRNGSeed(17)
        exclusions = capture_exclusions(mask_mode, manifest)
    except (
        ValueError,
        KeyError,
        AttributeError,
        OSError,
        TypeError,
        RuntimeError,
        sqlite3.Error,
    ) as error:
        if caller_failure[0] is not None:
            raise caller_failure[0]
        result["reason"] = str(error)[:160] or "endpoint_preparation_failed"
        return rec, result

    def read_frame(row):
        bounded()
        frame = recorded.get(row["source_index"])
        if (
            not frame
            or frame.get("sha256") != row.get("source_access_unit_sha256")
            or frame.get("relative_ticks_90k") != row.get("relative_ticks_90k")
        ):
            raise ValueError("frame_source_binding")
        offset, size = frame.get("offset"), frame.get("bytes")
        video = _safe_path(job, job / "input/video.h264", file=True, limit=2 * 1024**3)
        if (
            type(offset) is not int
            or type(size) is not int
            or offset < 0
            or size <= 0
            or size > 16 * 1024**2
            or offset + size > video.stat().st_size
        ):
            raise ValueError("frame_source_bounds")
        with video.open("rb") as stream:
            stream.seek(offset)
            if hashlib.sha256(stream.read(size)).hexdigest() != frame["sha256"]:
                raise ValueError("frame_access_unit_hash_mismatch")
        path = _safe_path(job, prepared / row["image"], file=True, limit=32 * 1024**2)
        if (
            not path.is_relative_to((prepared / "images").resolve())
            or path.stat().st_size > 32 * 1024**2
        ):
            raise ValueError("frame_path_invalid")
        if _sha(path) != row.get("png_sha256"):
            raise ValueError("frame_hash_mismatch")
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size > 24_000_000:
            raise ValueError("frame_invalid")
        return image

    try:
        for number, (_, _, row, original_anchor) in enumerate(targets[:MAX_VIEWS]):
            bounded()
            progress("endpoint_resection", number, min(MAX_VIEWS, len(targets)))
            anchor = candidate.images[original_anchor.image_id]
            anchor_row = by_name[anchor.name]
            first, second = read_frame(anchor_row), read_frame(row)
            if first.shape != second.shape:
                raise ValueError("frame_shape_mismatch")
            height, width = first.shape
            camera = candidate.cameras[anchor.camera_id]
            if (camera.width, camera.height) != (width, height):
                raise ValueError("camera_image_geometry_mismatch")
            values = [
                (int(v.point3D_id), v.xy)
                for v in anchor.points2D
                if v.has_point3D() and _inside(*_colmap_to_cv(v.xy), width, height, exclusions)
            ]
            values = sorted({pid: xy for pid, xy in values}.items())[:MAX_TRACKS]
            frame_report = dict(
                source_index=row["source_index"],
                anchor=anchor.name,
                anchor_tracks=len(values),
                accepted=False,
            )
            if len(values) < 45:
                frame_report["reason"] = "insufficient_landmarks"
                result["frames"].append(frame_report)
                continue
            points = np.asarray([_colmap_to_cv(xy) for _, xy in values], np.float32).reshape(
                -1, 1, 2
            )
            forward, status, _ = cv2.calcOpticalFlowPyrLK(
                first, second, points, None, winSize=(21, 21), maxLevel=3
            )
            back, back_status, _ = cv2.calcOpticalFlowPyrLK(
                second, first, forward, None, winSize=(21, 21), maxLevel=3
            )
            fb = np.linalg.norm((back - points).reshape(-1, 2), axis=1)
            kept = [
                i
                for i in range(len(values))
                if status[i, 0]
                and back_status[i, 0]
                and fb[i] <= 0.5
                and _inside(*forward[i, 0], width, height, exclusions)
            ]
            point_ids = np.asarray([values[i][0] for i in kept], np.uint64)
            xy = np.asarray([_cv_to_colmap(forward[i, 0]) for i in kept], np.float64).reshape(-1, 2)
            xyz = np.asarray(
                [candidate.points3D[int(i)].xyz for i in point_ids], np.float64
            ).reshape(-1, 3)
            frame_report["fb_pass"] = len(kept)
            pose, details = _fit_pose(point_ids, xy, xyz, camera, width, height)
            frame_report.update(details)
            if pose is not None:
                q = xyz @ pose.rotation.matrix().T + pose.translation
                error = np.linalg.norm(camera.img_from_cam(q) - xy, axis=1)
                valid = (q[:, 2] > 0) & np.isfinite(error) & (error <= 4.0)
                point_ids, xy = point_ids[valid], xy[valid]
                image_id = ids.get(Path(row["image"]).name)
                if image_id is None or image_id in candidate.images:
                    raise ValueError("image_id_collision")
                image = p.Image(
                    name=Path(row["image"]).name,
                    keypoints=xy,
                    camera_id=anchor.camera_id,
                    image_id=image_id,
                )
                candidate.add_image_with_trivial_frame(image, pose)
                for index, point_id in enumerate(point_ids):
                    candidate.add_observation(int(point_id), p.TrackElement(image_id, index))
                data = folder / f"{row['source_index']:08d}.npz"
                np.savez_compressed(
                    data,
                    point3d_ids=point_ids,
                    xy=xy,
                    train=np.asarray([_split(i) for i in point_ids], dtype=bool),
                    cam_from_world=pose.matrix(),
                )
                frame_report.update(
                    observations=len(point_ids),
                    observation_sha256=_sha(data),
                    source_access_unit_sha256=row["source_access_unit_sha256"],
                    png_sha256=row["png_sha256"],
                    ticks_90k=row["relative_ticks_90k"],
                    anchor_source_access_unit_sha256=anchor_row["source_access_unit_sha256"],
                    anchor_png_sha256=anchor_row["png_sha256"],
                )
            result["frames"].append(frame_report)
        bounded()
        if not any(x["accepted"] for x in result["frames"]):
            result["reason"] = "no_valid_pose"
            write_json(folder / "result.json", result)
            return rec, result
        _, assessment = model_assessment(
            candidate, prepared, selected, source_start, source_end, check=bounded
        )
        invalid = duplicate = negative = 0
        for point_id, point in candidate.points3D.items():
            bounded()
            seen = set()
            for element in point.track.elements:
                image = candidate.images[element.image_id]
                obs = image.points2D[element.point2D_idx]
                invalid += not obs.has_point3D() or obs.point3D_id != point_id
                duplicate += element.image_id in seen
                seen.add(element.image_id)
                pose = image.cam_from_world()
                negative += (pose.rotation.matrix() @ point.xyz + pose.translation)[2] <= 0
        for image_id in rec.reg_image_ids():
            old, new = rec.images[image_id], candidate.images[image_id]
            if not np.array_equal(old.cam_from_world().matrix(), new.cam_from_world().matrix()):
                raise ValueError("anchor_pose_changed")
            if len(old.points2D) != len(new.points2D) or any(
                a.point3D_id != b.point3D_id or not np.array_equal(a.xy, b.xy)
                for a, b in zip(old.points2D, new.points2D)
            ):
                raise ValueError("anchor_observations_changed")
        if any(
            not np.array_equal(v.xyz, candidate.points3D[k].xyz) for k, v in rec.points3D.items()
        ):
            raise ValueError("anchor_landmarks_changed")
        for point_id, point in rec.points3D.items():
            old = [(e.image_id, e.point2D_idx) for e in point.track.elements]
            new = [(e.image_id, e.point2D_idx) for e in candidate.points3D[point_id].track.elements]
            if new[: len(old)] != old:
                raise ValueError("anchor_tracks_changed")
        result.update(
            assessment=assessment,
            invalid_reciprocal=int(invalid),
            duplicate_image_in_track=int(duplicate),
            nonpositive_depth=int(negative),
        )
        result["accepted"] = bool(
            assessment["scene_admissible"]
            and assessment["route_admissible"]
            and not invalid
            and not duplicate
            and not negative
        )
        if result["accepted"]:
            (folder / "candidate").mkdir()
            candidate.write(folder / "candidate")
        else:
            result["reason"] = "candidate_quality_rejected"
    except (ValueError, KeyError, AttributeError, OSError, TypeError, RuntimeError) as error:
        if caller_failure[0] is not None:
            raise caller_failure[0]
        result["reason"] = str(error)[:160]
        result["accepted"] = False
    write_json(folder / "result.json", result)
    return (candidate if result["accepted"] else rec), result
