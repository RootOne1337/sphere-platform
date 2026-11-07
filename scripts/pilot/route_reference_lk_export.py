"""Source-bound measured-reference LK artifacts; never an autonomy approval."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from motor_worker.route_reference_lk import (
    CACHE_FILE,
    FAMILY,
    MAX_CACHE_BYTES,
    MAX_METADATA_BYTES,
    MAX_PER_VIEW,
    MAX_VIEWS,
    SCHEMA,
    SIZE,
    ReferenceLKRoute,
    canonical_hash,
    reference_lk_pipeline_id,
    reference_lk_support,
)

RECEIPT_SCHEMA = "sphere-reference-lk-export-v1"
QUALIFICATION_SCHEMA = "sphere-reference-lk-controlled-test-qualification-v1"
VALIDATION_SCHEMA = "sphere-reference-lk-offline-validation-v1"


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _regular(path, folder, maximum):
    path, folder = Path(path), Path(folder).resolve(strict=True)
    if not path.resolve(strict=True).is_relative_to(folder):
        raise ValueError("reference_lk_asset_path")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("reference_lk_asset_path")
        if part == folder:
            break
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("reference_lk_asset_quota")
    return path


def export(
    model,
    provenance,
    images,
    output,
    *,
    profile,
    world_revision,
    source_geometry_sha256,
    source_model_sha256,
    source_capture_sha256,
    checkpoint_fn,
    source_geometry_path=None,
):
    import cv2 as cv
    import numpy as np
    import pycolmap

    from motor_worker.policy import PolicyFrame
    from motor_worker.route_localization import feature_mask, prepare_feature_gray
    from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv
    from scripts.pilot.route_native_track_policy import audit_native_model

    started = time.monotonic()
    model, provenance, images, output = map(Path, (model, provenance, images, output))
    if output.exists() or (output.parent / CACHE_FILE).exists():
        raise FileExistsError("reference_lk_export_exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    def check():
        if time.monotonic() - started > 180:
            raise ValueError("reference_lk_export_time_quota")
        checkpoint_fn(output.resolve().parent)

    check()
    if any(path.is_symlink() or path.is_junction() for path in (model, provenance, images)):
        raise ValueError("reference_lk_asset_path")
    model_files = list(model.glob("*.bin"))
    if sum(path.stat().st_size for path in model_files) > 128 * 1024**2:
        raise ValueError("reference_lk_native_model_quota")
    for path in model_files:
        _regular(path, model, 128 * 1024**2)
    _regular(provenance, provenance.parent, 4 * 1024**2)
    if source_geometry_path is not None:
        _regular(Path(source_geometry_path), Path(source_geometry_path).parent, 32 * 1024**2)
    bins = {path.name: _hash(path) for path in sorted(model.glob("*.bin"))}
    if bins != source_model_sha256 or len(bins) != 5:
        raise ValueError("reference_lk_source_changed")
    if source_geometry_path is None or _hash(Path(source_geometry_path)) != source_geometry_sha256:
        raise ValueError("reference_lk_geometry_binding_required")
    source = json.loads(provenance.read_bytes())
    if source.get("source_manifest_sha256") != source_capture_sha256:
        raise ValueError("reference_lk_source_changed")
    manifest = _regular(
        provenance.parent.parent / "input/manifest.json", provenance.parent.parent, 4 * 1024**2
    )
    if _hash(manifest) != source_capture_sha256:
        raise ValueError("reference_lk_source_changed")
    source_index_sha = _hash(provenance)
    rows = {Path(row["image"]).name: row for row in source["images"]}
    rec = pycolmap.Reconstruction(model)
    if (
        rec.num_cameras() != 1
        or not 2 <= rec.num_reg_images() <= MAX_VIEWS
        or len(rows) != rec.num_reg_images()
    ):
        raise ValueError("reference_lk_native_model_quota")
    camera = next(iter(rec.cameras.values()))
    if camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"}:
        raise ValueError("reference_lk_pinhole_required")
    if camera.width * SIZE[1] != camera.height * SIZE[0]:
        raise ValueError("reference_lk_source_geometry")
    geometry = json.loads(Path(source_geometry_path).read_bytes())
    geometry_rows = {row["image"]: row for row in geometry["cameras"]}
    ordered = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if set(geometry_rows) != set(rows) or {im.name for im in ordered} != set(rows):
        raise ValueError("reference_lk_geometry_model_mismatch")
    audit = audit_native_model(rec, check=check)
    structural = audit["structural"]
    if structural["status"] != "complete" or any(
        structural[key]
        for key in (
            "duplicate_image_observations",
            "invalid_reciprocal_observations",
            "nonpositive_depth",
        )
    ):
        raise ValueError("reference_lk_native_observations_invalid")
    query_profile = replace(profile, width=SIZE[0], height=SIZE[1])
    mask = feature_mask(query_profile)
    K = colmap_calibration_to_opencv(
        camera.calibration_matrix(), (camera.width, camera.height), SIZE
    )
    grays, rgb_hashes, gray_hashes, pixels, xyz, ids, native_rows, offsets = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [0],
    )
    for im in ordered:
        check()
        native_matrix = im.cam_from_world().inverse().matrix()
        row = geometry_rows[im.name]
        if (
            not np.array_equal(native_matrix, np.asarray(row["camera_to_world"], np.float64))
            or row["ticks_90k"] != rows[im.name]["relative_ticks_90k"]
        ):
            raise ValueError("reference_lk_geometry_model_mismatch")
        path = _regular(images / im.name, images, 8 * 1024**2)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != rows[im.name]["png_sha256"]:
            raise ValueError("reference_lk_source_changed")
        bgr = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
        if bgr is None or bgr.shape[:2] != (camera.height, camera.width):
            raise ValueError("reference_lk_source_geometry")
        rgb = cv.cvtColor(cv.resize(bgr, SIZE, interpolation=cv.INTER_AREA), cv.COLOR_BGR2RGB)
        gray = prepare_feature_gray(
            PolicyFrame(world_revision, len(grays) + 1, 0.0, *SIZE, rgb.tobytes())
        )
        grays.append(gray)
        rgb_hashes.append(hashlib.sha256(rgb.tobytes()).hexdigest())
        gray_hashes.append(hashlib.sha256(gray.tobytes()).hexdigest())
        cells, seen = {}, set()
        for native_row, measurement in enumerate(im.points2D):
            if not measurement.has_point3D():
                continue
            identity = int(measurement.point3D_id)
            if identity not in rec.points3D or identity in seen:
                raise ValueError("reference_lk_native_observations_invalid")
            seen.add(identity)
            xy = (
                np.asarray(measurement.xy, np.float64)
                * np.asarray(SIZE)
                / [camera.width, camera.height]
                - 0.5
            )
            if not np.isfinite(xy).all() or (xy < 0).any() or (xy >= np.asarray(SIZE)).any():
                continue
            x, y = np.floor(xy + 0.5).astype(int)
            if not 0 <= x < SIZE[0] or not 0 <= y < SIZE[1] or mask[y, x] != 255:
                continue
            point = rec.points3D[identity]
            cells.setdefault((int(y * 8 / SIZE[1]), int(x * 12 / SIZE[0])), []).append(
                (
                    identity,
                    native_row,
                    xy,
                    point.xyz.copy(),
                    len(point.track.elements),
                    float(point.error),
                )
            )
        for cell in cells:
            cells[cell].sort(key=lambda item: (-item[4], item[5], item[0]))
        selected, layer = [], 0
        while len(selected) < MAX_PER_VIEW:
            added = 0
            for cell in sorted(cells):
                if layer < len(cells[cell]):
                    selected.append(cells[cell][layer])
                    added += 1
                if len(selected) >= MAX_PER_VIEW:
                    break
            if not added:
                break
            layer += 1
        if len(selected) < 24:
            raise ValueError("reference_lk_measured_support_insufficient")
        for identity, native_row, xy, world, _, _ in selected:
            ids.append(identity)
            native_rows.append(native_row)
            pixels.append(xy)
            xyz.append(world)
        offsets.append(len(ids))
    arrays = dict(
        grays=np.asarray(grays, np.uint8),
        mask=mask.astype(np.uint8),
        offsets=np.asarray(offsets, "<u4"),
        native_ids=np.asarray(ids, "<u8"),
        native_rows=np.asarray(native_rows, "<u4"),
        pixels=np.asarray(pixels, "<f4"),
        xyz=np.asarray(xyz, "<f8"),
    )
    if sum(value.nbytes for value in arrays.values()) > MAX_CACHE_BYTES:
        raise ValueError("reference_lk_cache_quota")
    cache_path = output.parent / CACHE_FILE
    with cache_path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    source_identity = dict(
        source_capture_sha256=source_capture_sha256,
        source_index_sha256=source_index_sha,
        source_geometry_sha256=source_geometry_sha256,
        model_sha256=bins,
    )
    data = dict(
        schema=SCHEMA,
        id=str(uuid.uuid4()),
        world_revision=world_revision,
        source_sha256=canonical_hash(source_identity),
        pipeline_sha256=reference_lk_pipeline_id(),
        profile=asdict(query_profile),
        intrinsics=[float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])],
        camera_trace=[im.cam_from_world().inverse().translation.tolist() for im in ordered],
        source_seconds=[rows[im.name]["relative_ticks_90k"] / 90000 for im in ordered],
        reference_rgb_sha256=rgb_hashes,
        source_frame_indices=[rows[im.name]["source_index"] for im in ordered],
        source_capture_sha256=source_capture_sha256,
        source_index_sha256=source_index_sha,
        source_geometry_sha256=source_geometry_sha256,
        model_sha256=sorted(bins.items()),
        reference_names=[im.name for im in ordered],
        source_png_sha256=[rows[im.name]["png_sha256"] for im in ordered],
        reference_gray_sha256=gray_hashes,
        native_row_counts=[im.num_points2D() for im in ordered],
        cache_sha256=_hash(cache_path),
        cache_file=CACHE_FILE,
        observations=len(ids),
        execution_qualified=False,
    )
    raw = (json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("reference_lk_metadata_quota")
    if (
        bins != {p.name: _hash(p) for p in model.glob("*.bin")}
        or _hash(provenance) != source_index_sha
        or _hash(Path(source_geometry_path)) != source_geometry_sha256
    ):
        raise ValueError("reference_lk_source_changed")
    with output.open("xb") as stream:
        stream.write(raw)
    artifact_sha = hashlib.sha256(raw).hexdigest()
    route = ReferenceLKRoute.load(output, sha256=artifact_sha)
    try:
        support = reference_lk_support(route)
    finally:
        route.close()
    check()
    return dict(
        schema=RECEIPT_SCHEMA,
        family=FAMILY,
        route_id=data["id"],
        sha256=artifact_sha,
        pipeline_sha256=data["pipeline_sha256"],
        cache_sha256=data["cache_sha256"],
        cache_file=CACHE_FILE,
        source_capture_sha256=source_capture_sha256,
        source_index_sha256=source_index_sha,
        geometry_sha256=source_geometry_sha256,
        model_sha256=bins,
        cameras=len(ordered),
        landmarks=len(set(ids)),
        observations=len(ids),
        first_seconds=data["source_seconds"][0],
        last_seconds=data["source_seconds"][-1],
        map_support=support,
        native_observation_audit=audit,
        metric_scale=None,
        camera_trace_only=True,
        input_events=0,
        execution_qualified=False,
        runtime_qualified=False,
        controlled_test_qualified=False,
        pixels="native_colmap_xy_scaled_minus_half_v1",
        seconds=time.monotonic() - started,
    )


def validate_reference_lk_receipt(
    receipt, folder, *, source_capture_sha256, source_index_sha256, geometry_sha256, model_sha256
):
    folder = Path(folder)
    if (
        type(receipt) is not dict
        or receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("family") != FAMILY
        or receipt.get("pipeline_sha256") != reference_lk_pipeline_id()
        or receipt.get("execution_qualified") is not False
        or receipt.get("source_capture_sha256") != source_capture_sha256
        or receipt.get("source_index_sha256") != source_index_sha256
        or receipt.get("geometry_sha256") != geometry_sha256
        or receipt.get("model_sha256") != model_sha256
        or receipt.get("cache_file") != CACHE_FILE
    ):
        raise ValueError("reference_lk_receipt_invalid")
    path = _regular(folder / "route.json", folder, MAX_METADATA_BYTES)
    if _hash(path) != receipt.get("sha256") or _hash(
        _regular(folder / CACHE_FILE, folder, MAX_CACHE_BYTES)
    ) != receipt.get("cache_sha256"):
        raise ValueError("reference_lk_receipt_invalid")
    data = json.loads(path.read_bytes())
    if (
        data["pipeline_sha256"] != reference_lk_pipeline_id()
        or data["source_capture_sha256"] != source_capture_sha256
        or data["source_index_sha256"] != source_index_sha256
        or data["source_geometry_sha256"] != geometry_sha256
        or dict(data["model_sha256"]) != model_sha256
        or data["cache_sha256"] != receipt["cache_sha256"]
    ):
        raise ValueError("reference_lk_receipt_invalid")
    return dict(
        family=FAMILY,
        pipeline_sha256=data["pipeline_sha256"],
        controlled_test_qualified=False,
        execution_qualified=False,
    )


def validate_reference_lk_qualification(receipt, folder, *, source_binding):
    folder = Path(folder)
    if not (folder / "controlled-test-qualification.json").exists():
        raise ValueError("route_reference_lk_unqualified")
    try:
        validate_reference_lk_receipt(
            receipt,
            folder,
            source_capture_sha256=source_binding["source_manifest_sha256"],
            source_index_sha256=source_binding["reconstruction_input_sha256"],
            geometry_sha256=source_binding["geometry_sha256"],
            model_sha256=source_binding["model_sha256"],
        )
    except (KeyError, TypeError) as error:
        raise ValueError("reference_lk_qualification_invalid") from error
    path = _regular(folder / "controlled-test-qualification.json", folder, 65536)
    q = json.loads(path.read_bytes())
    expected = dict(
        schema=QUALIFICATION_SCHEMA,
        scope="controlled_experimental_test_only",
        reviewed=True,
        execution_qualified=False,
        route_sha256=receipt["sha256"],
        cache_sha256=receipt["cache_sha256"],
        pipeline_sha256=reference_lk_pipeline_id(),
        source_binding_sha256=canonical_hash(source_binding),
    )
    if type(q) is not dict or any(
        q.get(key) != value or (type(value) is bool and type(q.get(key)) is not bool)
        for key, value in expected.items()
    ):
        raise ValueError("reference_lk_qualification_invalid")
    support = receipt.get("map_support") or {}
    if (
        support.get("all_reference_neighborhoods_supported") is not True
        or support.get("all_reference_intervals_observed") is not True
        or support.get("views_below_24") != 0
        or min(support.get("per_view_landmarks") or [0]) < 24
    ):
        raise ValueError("reference_lk_qualification_invalid")
    reports = {}
    for kind, name in (
        ("same_recording_heldout", "positive"),
        ("same_recording_heldout_transport", "transport"),
        ("unrelated_negative", "negative"),
    ):
        item = q.get(name + "_report") or {}
        filename = "reference-lk-" + name + ".json"
        if item.get("file") != filename:
            raise ValueError("reference_lk_qualification_invalid")
        report_path = _regular(folder / filename, folder, 2 * 1024**2)
        if _hash(report_path) != item.get("sha256"):
            raise ValueError("reference_lk_qualification_invalid")
        report = json.loads(report_path.read_bytes())
        if (
            report.get("schema") != VALIDATION_SCHEMA
            or report.get("kind") != kind
            or report.get("route_sha256") != receipt["sha256"]
            or report.get("cache_sha256") != receipt["cache_sha256"]
            or report.get("pipeline_sha256") != reference_lk_pipeline_id()
            or report.get("execution_qualified") is not False
            or type(report.get("sample_count")) is not int
            or not 1 <= report["sample_count"] <= 3000
        ):
            raise ValueError("reference_lk_qualification_invalid")
        samples = report.get("sample_rows")
        if type(samples) is not list or len(samples) != report["sample_count"]:
            raise ValueError("reference_lk_qualification_invalid")
        counts, identities = Counter(), set()
        for row in samples:
            if (
                type(row) is not dict
                or type(row.get("source_index")) is not int
                or not 0 <= row["source_index"] <= 72000
                or row["source_index"] in identities
                or not _valid_sha(row.get("source_rgb_sha256"))
                or not _valid_sha(row.get("actualdecoded_rgb_sha256"))
                or row.get("state") not in {"localized", "confirming", "unknown"}
                or type(row.get("compute_ms")) not in (int, float)
                or not 0 <= row["compute_ms"] <= 60000
            ):
                raise ValueError("reference_lk_qualification_invalid")
            identities.add(row["source_index"])
            counts[row["state"]] += 1
        if (
            type(report.get("counts")) is not dict
            or any(type(value) is not int or value < 0 for value in report["counts"].values())
            or {key: value for key, value in report.get("counts", {}).items() if value}
            != dict(counts)
        ):
            raise ValueError("reference_lk_qualification_invalid")
        freshness = report.get("freshness_lower_bound") or {}
        if (
            freshness.get("receiver_age_budget_ms") != 250
            or freshness.get("samples_exceeding_budget")
            != sum(r["compute_ms"] > 250 for r in samples)
            or freshness.get("localized_samples_exceeding_budget")
            != sum(r["compute_ms"] > 250 and r["state"] == "localized" for r in samples)
            or type(report.get("offline_media_clock")) is not bool
        ):
            raise ValueError("reference_lk_qualification_invalid")
        reports[name] = report
    positive, transport, negative = reports["positive"], reports["transport"], reports["negative"]
    metadata = json.loads((folder / "route.json").read_bytes())
    taught, references = (
        set(metadata["source_frame_indices"]),
        set(metadata["reference_rgb_sha256"]),
    )
    if (
        positive.get("source_capture_sha256") != receipt["source_capture_sha256"]
        or positive.get("offline_media_clock") is not True
        or positive.get("untaught_source_indices") is not True
        or positive.get("raw_rgb_source_bound") is not True
        or positive.get("freshness_lower_bound") is None
        or sum(positive.get("counts", {}).values()) != positive["sample_count"]
        or positive.get("counts", {}).get("localized", 0) < 1
        or negative.get("source_capture_sha256") == receipt["source_capture_sha256"]
        or not _valid_sha(negative.get("source_capture_sha256"))
        or negative.get("unrelated_sources") is not True
        or type(negative.get("false_pose_count")) is not int
        or negative.get("false_pose_count") != 0
        or negative.get("counts", {}).get("confirming", 0) != 0
        or negative.get("counts", {}).get("localized", 0) != 0
        or any(
            type(row.get("diagnostic")) is not dict
            or row["diagnostic"].get("method") != "measured_reference_lk"
            for row in negative["sample_rows"]
        )
        or any(row["actualdecoded_rgb_sha256"] in references for row in negative["sample_rows"])
        or any(row["source_index"] in taught for row in positive["sample_rows"])
        or transport.get("source_capture_sha256") != receipt["source_capture_sha256"]
        or transport.get("offline_media_clock") is not False
        or transport.get("counts", {}).get("localized", 0) < 1
        or transport.get("raw_rgb_source_bound") is not True
        or transport.get("untaught_source_indices") is not True
        or transport.get("transport") != dict(codec="jpeg", quality=86, width=960, height=540)
        or [(r["source_index"], r["source_rgb_sha256"]) for r in positive["sample_rows"]]
        != [(r["source_index"], r["source_rgb_sha256"]) for r in transport["sample_rows"]]
        or any(not _valid_sha(r.get("jpeg_sha256")) for r in transport["sample_rows"])
    ):
        raise ValueError("reference_lk_qualification_invalid")
    return dict(
        scope="controlled_experimental_test_only",
        controlled_test_qualified=True,
        execution_qualified=False,
        qualification_sha256=_hash(path),
        positive_report_sha256=q["positive_report"]["sha256"],
        transport_report_sha256=q["transport_report"]["sha256"],
        negative_report_sha256=q["negative_report"]["sha256"],
    )


def _valid_sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
