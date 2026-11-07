"""Exact native SIFT-row/POINT3D_ID export, without reassociation or triangulation.

The builder consumes only measured native rows and source-bound namespace maps.
It never mutates a reconstruction, database, pose, source PNG or input journal.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
import time
import zipfile
from collections import Counter, OrderedDict
from contextlib import closing
from pathlib import Path

from motor_worker.route_localization import (
    NATIVE_REFERENCE_EXPORT_VERSION as EXPORT_VERSION,
)
from motor_worker.route_localization import (
    NATIVE_REFERENCE_FAMILY as FAMILY,
)

MAX_VIEWS = 256
MAX_POINTS = 100_000
MAX_ROWS = 2_000_000
MAX_FEATURE_BYTES = 128 * 1024**2
MAX_MODEL_BYTES = 128 * 1024**2
MAX_SECONDS = 90
SIZE = (960, 540)
_VERIFIED = OrderedDict()


def _file_hash(path, checkpoint):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            checkpoint()
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path, root, maximum):
    path, root = Path(path), Path(root).resolve(strict=True)
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("native_bundle_path")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("native_bundle_path")
        if part == root:
            break
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("native_bundle_file_quota")
    return path


def _json(path, root, maximum=1024 * 1024):
    value = json.loads(_regular(path, root, maximum).read_bytes())
    if type(value) is not dict:
        raise ValueError("native_bundle_contract")
    return value


def selected_bundle(job, model, *, checkpoint):
    """Return the generic engine cache only for the exact selected model.

    An absent/rejected/unselected engine has an explicit legacy fallback reason.
    A malformed accepted, current-source cache is an error, never a silent
    reassociation attempt. No current-source artifact is written here.
    """
    job, model = Path(job), Path(model)
    folder = job / "prepared/fused-recovery"
    result = folder / "result.json"
    if not result.exists():
        return None, "native_bundle_absent"
    report = _json(result, job)
    if (
        type(report) is not dict
        or report.get("schema") != "sphere-fused-route-recovery-v1"
        or type(report.get("accepted")) is not bool
    ):
        raise ValueError("native_bundle_contract")
    if report["accepted"] is not True:
        return None, "native_engine_not_selected"
    protected = {}

    def bind(path, expected=None, maximum=512 * 1024**2):
        path = _regular(path, job, maximum)
        actual = _file_hash(path, checkpoint)
        if expected is not None and (not isinstance(expected, str) or actual != expected):
            raise ValueError("native_bundle_source_changed")
        protected[path] = actual
        return actual

    bind(result, maximum=1024 * 1024)
    manifest_sha = bind(
        job / "input/manifest.json", report.get("source_manifest_sha256"), maximum=65536
    )
    index_sha = bind(
        job / "prepared/reconstruction-input.json",
        report.get("reconstruction_input_sha256"),
        maximum=4 * 1024**2,
    )
    if (
        report.get("execution_qualified") is not False
        or report.get("source_modified") is not False
        or not isinstance(report.get("source_manifest_sha256"), str)
        or not isinstance(report.get("reconstruction_input_sha256"), str)
    ):
        raise ValueError("native_bundle_contract")
    bins = report.get("model_sha256")
    required = {"cameras.bin", "images.bin", "points3D.bin"}
    allowed = required | {"rigs.bin", "frames.bin"}
    if (
        type(bins) is not dict
        or not required <= set(bins)
        or not set(bins) <= allowed
        or any(not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v) for v in bins.values())
        or {p.name for p in (folder / "model").glob("*.bin")} != set(bins)
    ):
        raise ValueError("native_bundle_model")
    for name, expected in bins.items():
        bind(folder / "model" / name, expected, maximum=MAX_MODEL_BYTES)
    if sum((folder / "model" / name).stat().st_size for name in bins) > MAX_MODEL_BYTES:
        raise ValueError("native_bundle_model_quota")
    actual_bins = {p.name: bind(p) for p in model.glob("*.bin")}
    if actual_bins != bins:
        return None, "native_engine_model_not_selected_or_modified"
    paths = dict(
        namespace="namespace.json",
        row_mapping="row-remapping.npz",
        sift_database="sift.db",
        fused_database="database.db",
        mask_provenance="detector-masks.json",
    )
    expected_bundle = dict(
        model="model",
        namespace=paths["namespace"],
        row_mapping=paths["row_mapping"],
        sift_database=paths["sift_database"],
        float_features="sift-features",
        mask_provenance=paths["mask_provenance"],
    )
    assets = report.get("assets")
    if (
        report.get("native_landmark_bundle") != expected_bundle
        or type(assets) is not dict
        or set(assets) != set(paths)
    ):
        raise ValueError("native_bundle_assets")
    for name, relative in paths.items():
        item = assets[name]
        if (
            type(item) is not dict
            or set(item) != {"path", "sha256"}
            or item["path"] != relative
            or not isinstance(item["sha256"], str)
            or not re.fullmatch("[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("native_bundle_assets")
        bind(
            folder / relative,
            item["sha256"],
            maximum=512 * 1024**2 if name.endswith("database") else 16 * 1024**2,
        )
    namespace = _json(folder / paths["namespace"], job, 2 * 1024**2)
    if (
        namespace.get("schema") != "sphere-fused-route-namespace-v1"
        or namespace.get("sift_descriptors") != "quantized_rootsift_round512_uint8"
        or namespace.get("source_sift_database_sha256") != assets["sift_database"]["sha256"]
        or namespace.get("row_remapping_sha256") != assets["row_mapping"]["sha256"]
        or type(namespace.get("images")) is not list
        or not 3 <= len(namespace["images"]) <= MAX_VIEWS
    ):
        raise ValueError("native_bundle_descriptor_family")
    source = _json(job / "prepared/reconstruction-input.json", job, 4 * 1024**2)
    if (
        source.get("source_manifest_sha256") != manifest_sha
        or type(source.get("images")) is not list
        or len(source["images"]) != len(namespace["images"])
        or any(
            type(row) is not dict or type(row.get("image")) is not str for row in source["images"]
        )
    ):
        raise ValueError("native_bundle_source_changed")
    source_rows = {Path(row["image"]).name: row for row in source["images"]}
    if any(
        type(row) is not dict or type(row.get("name")) is not str for row in namespace["images"]
    ):
        raise ValueError("native_bundle_image_namespace")
    names = [row.get("name") for row in namespace["images"]]
    if len(set(names)) != len(names) or set(names) != set(source_rows):
        raise ValueError("native_bundle_image_namespace")
    for row in namespace["images"]:
        name = row["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[0-9]{8}\.png", name):
            raise ValueError("native_bundle_image_namespace")
        if not isinstance(source_rows[name].get("png_sha256"), str) or not re.fullmatch(
            "[0-9a-f]{64}", source_rows[name]["png_sha256"]
        ):
            raise ValueError("native_bundle_source_changed")
        bind(
            job / "prepared/images" / name, source_rows[name].get("png_sha256"), maximum=8 * 1024**2
        )
        if row.get("sourcePngSHA") != source_rows[name].get("png_sha256"):
            raise ValueError("native_bundle_source_changed")
    masks = _json(folder / paths["mask_provenance"], job, 2 * 1024**2)
    manifest = _json(job / "input/manifest.json", job, 65536)
    config = manifest.get("config") or {}
    if type(config) is not dict:
        raise ValueError("native_bundle_mask_provenance")
    profile = config.get("profile") or {}
    if type(profile) is not dict:
        raise ValueError("native_bundle_mask_provenance")
    expected_profile = dict(
        mode=profile.get("mode"),
        hudProfile=profile.get("hudProfile"),
        hud_hidden_declared=config.get("hud_hidden_declared"),
    )
    if (
        masks.get("schema") != "sphere-fused-detector-masks-v1"
        or masks.get("source_manifest_sha256") != manifest_sha
        or masks.get("reconstruction_input_sha256") != index_sha
        or masks.get("detector_footer_exclusion_y") != 0.975
        or masks.get("supplied_mask_producer") != "unknown_hash_bound_pixels"
        or masks.get("declared_profile") != expected_profile
        or type(masks.get("producer_sources")) is not dict
        or not masks["producer_sources"]
        or any(
            not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v)
            for v in masks["producer_sources"].values()
        )
        or type(masks.get("images")) is not list
        or len(masks["images"]) != len(names)
        or any(
            type(row) is not dict or type(row.get("image")) is not str for row in masks["images"]
        )
    ):
        raise ValueError("native_bundle_mask_provenance")
    mask_rows = {row["image"]: row for row in masks["images"]}
    if len(mask_rows) != len(names) or set(mask_rows) != set(names):
        raise ValueError("native_bundle_mask_provenance")
    for name, row in mask_rows.items():
        item = row.get("effective_mask")
        if (
            type(item) is not dict
            or set(item) != {"path", "sha256"}
            or item["path"] != "detector-masks/" + name
        ):
            raise ValueError("native_bundle_mask_provenance")
        if not isinstance(item["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", item["sha256"]):
            raise ValueError("native_bundle_mask_provenance")
        bind(folder / item["path"], item["sha256"], maximum=8 * 1024**2)
    extractor = Path(__file__).with_name("learned_route_features.py")
    extractor_key = "scripts/pilot/learned_route_features.py"
    if masks["producer_sources"].get(extractor_key) != _file_hash(extractor, checkpoint):
        raise ValueError("native_bundle_descriptor_recipe_changed")
    checkpoint()
    return dict(
        folder=folder,
        model=model,
        namespace=namespace["images"],
        source=source,
        source_manifest_sha256=manifest_sha,
        source_index_sha256=index_sha,
        model_sha256=bins,
        assets=assets,
        masks=mask_rows,
        protected=protected,
        extractor=extractor,
        extractor_sha256=masks["producer_sources"][extractor_key],
    ), "exact_native_bundle_selected"


def verify_bundle_unchanged(bundle, *, checkpoint):
    if _file_hash(bundle["extractor"], checkpoint) != bundle["extractor_sha256"]:
        raise ValueError("native_bundle_descriptor_recipe_changed")
    for path, expected in bundle["protected"].items():
        _regular(path, bundle["folder"].parents[1], 512 * 1024**2)
        if _file_hash(path, checkpoint) != expected:
            raise ValueError("native_bundle_source_changed")


def export(bundle, provenance, images, output, *, profile, world_revision, checkpoint_fn):
    """Export measured native IDs; decode RGB only for reference-image hashes.

    This path invokes no detector, matching, pose refinement or triangulation.
    prepare() owns the final receipt/state publication and resource admission.
    """
    import uuid

    import cv2 as cv
    import numpy as np
    import pycolmap

    from motor_worker.route_localization import (
        SparseRoute,
        feature_mask,
        map_support,
        native_reference_pipeline_id,
        pipeline_id,
    )
    from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv
    from scripts.pilot.reconstruction_quality import pinhole_condition

    began = time.monotonic()
    output, images, provenance = Path(output), Path(images), Path(provenance)

    def check():
        if time.monotonic() - began > 300:
            raise ValueError("sparse_export_time_quota")
        checkpoint_fn(output.resolve().parent)

    if output.exists() or (output.parent / "native-landmarks.json.gz").exists():
        raise FileExistsError("native_export_exists")
    check()
    verify_bundle_unchanged(bundle, checkpoint=check)
    if _file_hash(provenance, check) != bundle["source_index_sha256"]:
        raise ValueError("native_bundle_source_changed")
    rec = pycolmap.Reconstruction(bundle["model"])
    if rec.num_cameras() != 1 or not 3 <= rec.num_reg_images() <= MAX_VIEWS:
        raise ValueError("native_landmark_model_quota")
    camera = next(iter(rec.cameras.values()))
    original_K = camera.calibration_matrix()
    if (
        camera.width * SIZE[1] != camera.height * SIZE[0]
        or not pinhole_condition(
            camera.width, camera.height, float(original_K[0, 0]), float(original_K[1, 1])
        )["passed"]
    ):
        raise ValueError("camera_intrinsics_degenerate")
    K = colmap_calibration_to_opencv(original_K, (camera.width, camera.height), SIZE)
    rows = {Path(row["image"]).name: row for row in bundle["source"]["images"]}
    ordered = sorted(rec.images.values(), key=lambda im: rows[im.name]["relative_ticks_90k"])
    if set(rows) != {im.name for im in ordered}:
        raise ValueError("native_bundle_image_namespace")
    features, remaps = read_feature_cache(
        bundle["folder"] / "sift.db",
        bundle["folder"] / "row-remapping.npz",
        bundle["namespace"],
        checkpoint=check,
    )
    for row in bundle["namespace"]:
        check()
        metadata = bundle["masks"][row["name"]]
        raw = (bundle["folder"] / metadata["effective_mask"]["path"]).read_bytes()
        detector = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_GRAYSCALE)
        if (
            detector is None
            or detector.shape != (camera.height, camera.width)
            or metadata.get("width") != camera.width
            or metadata.get("height") != camera.height
            or not np.isin(detector, (0, 255)).all()
            or np.any(detector[int(camera.height * 0.975) :])
        ):
            raise ValueError("native_bundle_mask_provenance")
        xy = features[row["siftImageId"]][0][:, :2].astype(np.float64) - 0.5
        pixels = np.floor(xy + 0.5).astype(np.int64)
        if (
            np.any(pixels < 0)
            or np.any(pixels[:, 0] >= camera.width)
            or np.any(pixels[:, 1] >= camera.height)
            or np.any(detector[pixels[:, 1], pixels[:, 0]] != 255)
        ):
            raise ValueError("native_bundle_detector_mask_binding")
    mask, proof = feature_mask(profile), []
    candidates, report, ids = build(
        rec,
        ordered,
        features,
        bundle["namespace"],
        remaps,
        K,
        mask=mask,
        checkpoint=check,
        provenance=proof,
    )
    matrices = [im.cam_from_world().matrix() for im in ordered]
    selected, selection = select_balanced(candidates, ids, matrices, K, checkpoint=check)
    reference_hashes = []
    for image in ordered:
        check()
        raw = (images / image.name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != rows[image.name]["png_sha256"]:
            raise ValueError("native_bundle_source_changed")
        bgr = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
        if bgr is None or bgr.shape[:2] != (camera.height, camera.width):
            raise ValueError("native_bundle_image_decode")
        rgb = cv.cvtColor(
            cv.resize(bgr, (profile.width, profile.height), interpolation=cv.INTER_AREA),
            cv.COLOR_BGR2RGB,
        )
        reference_hashes.append(hashlib.sha256(rgb.tobytes()).hexdigest())
    binding = dict(
        model=bundle["model_sha256"],
        namespace=bundle["assets"]["namespace"]["sha256"],
        row_mapping=bundle["assets"]["row_mapping"]["sha256"],
        sift_database=bundle["assets"]["sift_database"]["sha256"],
        mask=_hash(mask),
    )
    seconds = tuple(rows[image.name]["relative_ticks_90k"] / 90000 for image in ordered)
    route = SparseRoute(
        str(uuid.uuid4()),
        world_revision,
        _digest(binding),
        native_reference_pipeline_id(),
        profile,
        (float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2])),
        tuple(candidates[i][1] for i in selected),
        np.asarray([candidates[i][2] for i in selected], dtype="<f4").tobytes(),
        tuple(
            tuple(float(v) for v in image.cam_from_world().inverse().translation)
            for image in ordered
        ),
        seconds,
        tuple(reference_hashes),
        tuple(candidates[i][3] for i in selected),
        bundle["source_manifest_sha256"],
        tuple(rows[image.name]["source_index"] for image in ordered),
    )
    verify_bundle_unchanged(bundle, checkpoint=check)
    check()
    route_sha = route.save(output)
    proof_data = dict(
        schema="sphere-native-landmark-provenance-v1",
        runtime_qualified=False,
        route_sha256=route_sha,
        cache_binding_sha256=_digest(binding),
        pipeline_sha256=route.pipeline_sha256,
        source_manifest_sha256=route.source_capture_sha256,
        source_index_sha256=bundle["source_index_sha256"],
        detector_mask_provenance_sha256=bundle["assets"]["mask_provenance"]["sha256"],
        row_fingerprints=report.pop("row_fingerprints"),
        landmarks=[proof[i] for i in selected],
    )
    raw = json.dumps(proof_data, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 32 * 1024**2:
        raise ValueError("native_export_provenance_quota")
    compressed = gzip.compress(raw, mtime=0)
    if len(compressed) > 8 * 1024**2:
        raise ValueError("native_export_provenance_quota")
    path = output.parent / "native-landmarks.json.gz"
    with path.open("xb") as target:
        target.write(compressed)
    receipt = dict(
        schema="sphere-sparse-export-receipt-v1",
        route_id=route.id,
        sha256=route_sha,
        source_capture_sha256=route.source_capture_sha256,
        pipeline_sha256=route.pipeline_sha256,
        source_bindings=dict(
            bundle_result=bundle["protected"][bundle["folder"] / "result.json"],
            provenance=bundle["source_index_sha256"],
            **bundle["model_sha256"],
        ),
        landmarks=len(selected),
        cameras=len(ordered),
        first_seconds=seconds[0],
        last_seconds=seconds[-1],
        camera_trace_only=True,
        omitted_landmarks=len(candidates) - len(selected),
        feature_build=report,
        feature_selection=selection,
        map_support=map_support(route),
        metric_scale=None,
        pixel_coordinates="opencv_integer_centers_v1",
        execution_qualified=False,
        input_events=0,
        native_reference=dict(
            schema="sphere-native-reference-contract-v1",
            runtime_qualified=False,
            descriptor_family=FAMILY,
            export_version=EXPORT_VERSION,
            query_pipeline_sha256=pipeline_id(),
            pipeline_sha256=route.pipeline_sha256,
            source_manifest_sha256=route.source_capture_sha256,
            source_index_sha256=bundle["source_index_sha256"],
            cache_binding=binding,
            cache_binding_sha256=_digest(binding),
            provenance=dict(file=path.name, sha256=hashlib.sha256(compressed).hexdigest()),
        ),
    )
    validate_reference_receipt(
        receipt,
        output.parent,
        source_sha256=route.source_capture_sha256,
        source_index_sha256=bundle["source_index_sha256"],
    )
    check()
    return receipt


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_reference_receipt(receipt, folder, *, source_sha256, source_index_sha256):
    """Validate the exact family and immutable exported cache, not an ID prefix.

    This reads no native database/model and performs no extraction at status
    time. Expensive proof decoding is cached only by its measured content SHA;
    capture/index/pipeline/receipt bindings are checked on every call.
    """
    from motor_worker.route_localization import (
        MAX_BYTES,
        SparseRoute,
        native_reference_pipeline_id,
        pipeline_id,
    )

    block = receipt.get("native_reference")
    keys = {
        "schema",
        "runtime_qualified",
        "descriptor_family",
        "export_version",
        "query_pipeline_sha256",
        "pipeline_sha256",
        "source_manifest_sha256",
        "source_index_sha256",
        "cache_binding",
        "cache_binding_sha256",
        "provenance",
    }
    if (
        type(block) is not dict
        or set(block) != keys
        or block.get("schema") != "sphere-native-reference-contract-v1"
        or block.get("runtime_qualified") is not False
        or block.get("descriptor_family") != FAMILY
        or block.get("export_version") != EXPORT_VERSION
        or block.get("query_pipeline_sha256") != pipeline_id()
        or block.get("pipeline_sha256") != native_reference_pipeline_id()
        or receipt.get("pipeline_sha256") != native_reference_pipeline_id()
        or block.get("source_manifest_sha256") != source_sha256
        or block.get("source_index_sha256") != source_index_sha256
    ):
        raise ValueError("route_native_reference_invalid")
    binding = block["cache_binding"]
    if (
        type(binding) is not dict
        or set(binding) != {"model", "namespace", "row_mapping", "sift_database", "mask"}
        or type(binding["model"]) is not dict
        or not {"cameras.bin", "images.bin", "points3D.bin"} <= set(binding["model"])
        or not set(binding["model"])
        <= {"cameras.bin", "images.bin", "points3D.bin", "rigs.bin", "frames.bin"}
        or any(
            not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v)
            for v in [
                *binding["model"].values(),
                *(binding[k] for k in ("namespace", "row_mapping", "sift_database", "mask")),
            ]
        )
        or block["cache_binding_sha256"] != _digest(binding)
    ):
        raise ValueError("route_native_reference_invalid")
    proof = block["provenance"]
    if (
        type(proof) is not dict
        or set(proof) != {"file", "sha256"}
        or proof["file"] != "native-landmarks.json.gz"
    ):
        raise ValueError("route_native_reference_invalid")
    folder = Path(folder)
    route_path = _regular(folder / "route.json", folder, MAX_BYTES)
    if _file_hash(route_path, lambda: None) != receipt.get("sha256"):
        raise ValueError("route_native_reference_invalid")
    path = folder / proof["file"]
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or path.parent.is_junction()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 8 * 1024**2
    ):
        raise ValueError("route_native_reference_invalid")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != proof["sha256"]:
        raise ValueError("route_native_reference_invalid")
    key = (
        proof["sha256"],
        block["cache_binding_sha256"],
        source_sha256,
        source_index_sha256,
        pipeline_id(),
        receipt.get("sha256"),
        receipt.get("cameras"),
        receipt.get("landmarks"),
    )
    if key in _VERIFIED:
        _VERIFIED.move_to_end(key)
        return
    route = SparseRoute.load(route_path, sha256=receipt["sha256"])
    if (
        route.pipeline_sha256 != block["pipeline_sha256"]
        or route.source_capture_sha256 != source_sha256
        or len(route.camera_trace) != receipt.get("cameras")
        or len(route.points) != receipt.get("landmarks")
    ):
        raise ValueError("route_native_reference_invalid")
    with gzip.open(path, "rb") as stream:
        decoded = stream.read(32 * 1024**2 + 1)
    if len(decoded) > 32 * 1024**2:
        raise ValueError("route_native_reference_invalid")
    data = json.loads(decoded)
    count, views = receipt.get("landmarks"), receipt.get("cameras")
    if (
        type(count) is not int
        or not 24 <= count <= 4096
        or type(views) is not int
        or not 3 <= views <= MAX_VIEWS
        or type(data) is not dict
        or data.get("schema") != "sphere-native-landmark-provenance-v1"
        or data.get("route_sha256") != receipt.get("sha256")
        or data.get("cache_binding_sha256") != block["cache_binding_sha256"]
        or data.get("pipeline_sha256") != block["pipeline_sha256"]
        or data.get("source_manifest_sha256") != source_sha256
        or data.get("source_index_sha256") != source_index_sha256
        or data.get("runtime_qualified") is not False
        or type(data.get("landmarks")) is not list
        or len(data["landmarks"]) != count
    ):
        raise ValueError("route_native_reference_invalid")
    seen, seen_rows = set(), set()
    for point in data["landmarks"]:
        if type(point) is not dict:
            raise ValueError("route_native_reference_invalid")
        identity, rows = point.get("point3D_id"), point.get("observations")
        if (
            type(identity) is not str
            or not re.fullmatch(r"0|[1-9][0-9]{0,19}", identity)
            or int(identity) >= 2**64 - 1
            or identity in seen
            or type(rows) is not list
            or not 3 <= len(rows) <= views
            or point.get("descriptor_observation") not in rows
        ):
            raise ValueError("route_native_reference_invalid")
        seen.add(identity)
        actual = set()
        for row in rows:
            if (
                type(row) is not dict
                or type(row.get("view")) is not int
                or not 0 <= row["view"] < views
                or row["view"] in actual
                or any(
                    type(row.get(k)) is not int or row[k] < 0
                    for k in ("native_image_id", "fused_row", "sift_image_id", "sift_row")
                )
                or row["sift_row"] >= 4096
                or type(row.get("reprojection_px")) not in (int, float)
                or not 0 <= row["reprojection_px"] <= 3
            ):
                raise ValueError("route_native_reference_invalid")
            identity = (row["native_image_id"], row["fused_row"])
            if identity in seen_rows:
                raise ValueError("route_native_reference_invalid")
            seen_rows.add(identity)
            actual.add(row["view"])
    _VERIFIED[key] = True
    while len(_VERIFIED) > 8:
        _VERIFIED.popitem(last=False)


def read_feature_cache(database, mapping_file, namespace, *, checkpoint):
    """Bounded, read-only SQLite/NPZ cache, not a detector invocation."""
    import numpy as np

    database, mapping_file = Path(database), Path(mapping_file)
    for path, maximum in ((database, 512 * 1024**2), (mapping_file, 16 * 1024**2)):
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
            raise ValueError("native_cache_file_quota")
    if database.with_name(database.name + "-wal").exists():
        raise ValueError("native_cache_not_sealed")
    with zipfile.ZipFile(mapping_file) as archive:
        entries = archive.infolist()
        if (
            len(entries) > MAX_VIEWS * 2
            or sum(row.file_size for row in entries) > 32 * 1024**2
            or any(
                row.filename != Path(row.filename).name or not row.filename.endswith(".npy")
                for row in entries
            )
        ):
            raise ValueError("native_cache_mapping_quota")
    features, remaps, used = {}, {}, 0
    if not 3 <= len(namespace) <= MAX_VIEWS:
        raise ValueError("native_cache_view_quota")
    with (
        closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as db,
        np.load(mapping_file, allow_pickle=False) as maps,
    ):
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA cache_size=-4096")
        for row in namespace:
            checkpoint()
            identity = row["siftImageId"]
            if (
                type(identity) is not int
                or identity <= 0
                or type(row["siftRows"]) is not int
                or not 1 <= row["siftRows"] <= 4096
                or not isinstance(row["name"], str)
                or not re.fullmatch(r"[0-9]{8}\.png", row["name"])
                or identity in features
            ):
                raise ValueError("native_cache_database_namespace")
            image = db.execute("SELECT name FROM images WHERE image_id=?", (identity,)).fetchone()
            keypoints = db.execute(
                "SELECT rows,cols,length(data) FROM keypoints WHERE image_id=?", (identity,)
            ).fetchone()
            desc = db.execute(
                "SELECT type,rows,cols,length(data) FROM descriptors WHERE image_id=?", (identity,)
            ).fetchone()
            if (
                image != (row["name"],)
                or keypoints is None
                or desc is None
                or desc[0] != 0
                or keypoints[:2] != (row["siftRows"], 4)
                or desc[1:3] != (row["siftRows"], 128)
                or keypoints[2] != row["siftRows"] * 16
                or desc[3] != row["siftRows"] * 128
            ):
                raise ValueError("native_cache_database_namespace")
            used += keypoints[2] + desc[3]
            if used > MAX_FEATURE_BYTES:
                raise ValueError("native_landmark_feature_quota")
            name = f"sift_{identity}"
            mapping = maps[name].copy()
            if mapping.dtype.kind not in "iu" or mapping.shape != (row["siftRows"],):
                raise ValueError("native_cache_mapping_rows")
            xy_blob = db.execute(
                "SELECT data FROM keypoints WHERE image_id=?", (identity,)
            ).fetchone()[0]
            descriptor_blob = db.execute(
                "SELECT data FROM descriptors WHERE image_id=?", (identity,)
            ).fetchone()[0]
            features[identity] = (
                np.frombuffer(xy_blob, dtype="<f4").reshape(-1, 4),
                np.frombuffer(descriptor_blob, dtype=np.uint8).reshape(-1, 128),
            )
            remaps[name] = mapping
    return features, remaps


def select_balanced(candidates, point_ids, matrices, K, *, limit=4096, checkpoint):
    """Measured per-view support first; fill remaining budget across time/grid."""
    import numpy as np

    from scripts.pilot.route_landmark_builder import select_spatially_diverse

    if (
        type(limit) is not int
        or not 1 <= limit <= 4096
        or len(candidates) > MAX_POINTS
        or len(point_ids) != len(candidates)
        or len(set(point_ids)) != len(point_ids)
        or not 3 <= len(matrices) <= MAX_VIEWS
    ):
        raise ValueError("native_selection_quota")
    order = sorted(range(len(candidates)), key=lambda i: (-len(candidates[i][3]), point_ids[i]))
    by_view = [[] for _ in matrices]
    scores = np.zeros(len(order), np.int16)
    for rank, index in enumerate(order):
        if rank % 256 == 0:
            checkpoint()
        views = candidates[index][3]
        if (
            tuple(sorted(set(views))) != views
            or len(views) < 3
            or any(type(v) is not int or not 0 <= v < len(matrices) for v in views)
        ):
            raise ValueError("native_selection_views")
        scores[rank] = len(views)
        for view in views:
            by_view[view].append(rank)
    needed = np.full(len(matrices), 24, np.int32)
    selected = []
    while len(selected) < min(limit, len(order)) and len(scores) and scores.max() > 0:
        if len(selected) % 64 == 0:
            checkpoint()
        rank = int(np.argmax(scores))
        index = order[rank]
        selected.append(index)
        for view in candidates[index][3]:
            if needed[view] > 0:
                needed[view] -= 1
                if needed[view] == 0:
                    scores[by_view[view]] -= 1
        scores[rank] = -MAX_VIEWS
    chosen = set(selected)
    remaining = [candidates[index] for index in order if index not in chosen]
    if remaining and len(selected) < limit:
        extra, _ = select_spatially_diverse(
            remaining, matrices, K, limit - len(selected), checkpoint=checkpoint
        )
        identities = {id(row): index for index, row in enumerate(candidates)}
        selected.extend(identities[id(row)] for row in extra)
    support = [
        sum(view in candidates[index][3] for index in selected) for view in range(len(matrices))
    ]
    checkpoint()
    return selected, dict(
        strategy="native_view24_then_time_image_grid_v1",
        maximum=limit,
        candidate_count=len(candidates),
        selected_count=len(selected),
        support_per_view=support,
        minimum_view_support=min(support),
        views_below_24=sum(n < 24 for n in support),
        native_ids_preserved=True,
    )


def _hash(array):
    return hashlib.sha256(array.tobytes()).hexdigest()


def build(rec, ordered, features, namespace, remaps, K, *, mask, checkpoint, provenance=None):
    """Return (native candidates, compact audit, exact native IDs/measurements).

    features[siftImageId] = (native COLMAP float32 keypoint rows, uint8 q512
    RootSIFT descriptors). remaps['sift_<id>'] preserves original row indices.
    Only complete SIFT-suffix tracks are eligible; VIDEO-prefix aliases are not
    converted into SIFT landmarks. The selected descriptor is a measured medoid.
    """
    import numpy as np

    from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv

    began = time.monotonic()

    def check():
        if time.monotonic() - began > MAX_SECONDS:
            raise ValueError("native_landmark_time_quota")
        checkpoint()

    check()
    if (
        not 3 <= len(ordered) <= MAX_VIEWS
        or len(rec.points3D) > MAX_POINTS
        or len(namespace) != len(ordered)
        or len({im.image_id for im in ordered}) != len(ordered)
    ):
        raise ValueError("native_landmark_model_quota")
    mask = np.asarray(mask)
    K = np.asarray(K, dtype=np.float64)
    if (
        mask.shape != (SIZE[1], SIZE[0])
        or mask.dtype != np.uint8
        or not np.isin(mask, (0, 255)).all()
    ):
        raise ValueError("native_landmark_mask")
    if K.shape != (3, 3) or not np.isfinite(K).all():
        raise ValueError("native_landmark_calibration")
    names = {row["name"]: row for row in namespace}
    if len(names) != len(ordered) or set(names) != {im.name for im in ordered}:
        raise ValueError("native_landmark_image_namespace")
    matrices, inverses, observations, view_ids = [], [], [], {}
    total_rows, feature_bytes = 0, 0
    row_fingerprints = []
    for view, image in enumerate(ordered):
        check()
        row = names[image.name]
        sid, vid = row["siftImageId"], row["videoImageId"]
        if (
            type(sid) is not int
            or type(vid) is not int
            or vid != image.image_id
            or vid in view_ids
            or type(row["videoRows"]) is not int
            or row["videoRows"] < 0
            or type(row["siftRows"]) is not int
            or not 1 <= row["siftRows"] <= 4096
            or type(row["fusedRows"]) is not int
            or row["fusedRows"] != len(image.points2D)
        ):
            raise ValueError("native_landmark_row_namespace")
        xy, desc = features[sid]
        xy, desc, mapping = np.asarray(xy), np.asarray(desc), np.asarray(remaps[f"sift_{sid}"])
        n = row["siftRows"]
        feature_bytes += xy.nbytes + desc.nbytes + mapping.nbytes
        total_rows += len(image.points2D)
        if total_rows > MAX_ROWS or feature_bytes > MAX_FEATURE_BYTES:
            raise ValueError("native_landmark_feature_quota")
        if (
            xy.shape != (n, 4)
            or xy.dtype != np.float32
            or not np.isfinite(xy).all()
            or desc.shape != (n, 128)
            or desc.dtype != np.uint8
            or mapping.shape != (n,)
            or mapping.dtype.kind not in "iu"
            or (mapping < 0).any()
            or (mapping >= len(image.points2D)).any()
        ):
            raise ValueError("native_landmark_feature_rows")
        native_xy = np.asarray([p.xy for p in image.points2D], dtype=np.float32).reshape(-1, 2)
        if not np.isfinite(native_xy).all() or not np.array_equal(native_xy[mapping], xy[:, :2]):
            raise ValueError("native_landmark_exact_xy_binding")
        camera = rec.cameras[image.camera_id]
        if camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"}:
            raise ValueError("native_landmark_camera_model")
        expected = colmap_calibration_to_opencv(
            camera.calibration_matrix(), (camera.width, camera.height), SIZE
        )
        if not np.allclose(expected, K, rtol=0, atol=1e-8):
            raise ValueError("native_landmark_calibration_binding")
        matrix = np.asarray(image.cam_from_world().matrix(), dtype=np.float64)
        if (
            matrix.shape != (3, 4)
            or not np.isfinite(matrix).all()
            or not np.allclose(matrix[:, :3] @ matrix[:, :3].T, np.eye(3), atol=1e-6)
            or not np.isclose(np.linalg.det(matrix[:, :3]), 1.0, atol=1e-6)
        ):
            raise ValueError("native_landmark_pose")
        inverse = np.full(len(image.points2D), -1, np.int32)
        for original, fused in enumerate(mapping):
            if fused < row["videoRows"]:
                continue
            inverse[fused] = original if inverse[fused] == -1 else -2
        # Native COLMAP corner centers -> resized OpenCV integer centers ONCE.
        pixels = (
            xy[:, :2].astype(np.float64)
            * np.array([SIZE[0] / camera.width, SIZE[1] / camera.height])
            - 0.5
        )
        matrices.append(matrix)
        inverses.append(inverse)
        observations.append((pixels, desc, row, image))
        view_ids[vid] = view
        row_fingerprints.append(
            dict(
                name=image.name,
                native_image_id=vid,
                sift_image_id=sid,
                native_xy_sha256=_hash(native_xy),
                sift_rows_sha256=_hash(xy),
                descriptor_rows_sha256=_hash(desc),
                remapping_sha256=_hash(mapping),
            )
        )
    if len(set(row["siftImageId"] for row in namespace)) != len(namespace):
        raise ValueError("native_landmark_duplicate_sift_image")
    candidates, ids, proofs, rejected = [], [], [], Counter()
    seen_features = set()
    native_observations = 0
    for index, (point_id, point) in enumerate(rec.points3D.items()):
        if index % 64 == 0:
            check()
        elements = list(point.track.elements)
        native_observations += len(elements)
        if native_observations > MAX_ROWS:
            raise ValueError("native_landmark_observation_quota")
        views, samples, rays, measurements = [], [], [], []
        xyz = np.asarray(point.xyz, dtype=np.float64)
        if xyz.shape != (3,) or not np.isfinite(xyz).all() or (np.abs(xyz) > 1e8).any():
            raise ValueError("native_landmark_xyz")
        reason = None
        for element in elements:
            image_id, fused = int(element.image_id), int(element.point2D_idx)
            if image_id not in view_ids:
                raise ValueError("native_landmark_unregistered_track")
            view = view_ids[image_id]
            pixels, desc, row, image = observations[view]
            if not 0 <= fused < len(image.points2D):
                raise ValueError("native_landmark_track_row")
            native = image.points2D[fused]
            if not native.has_point3D() or int(native.point3D_id) != int(point_id):
                raise ValueError("native_landmark_reciprocity")
            if view in views or (image_id, fused) in seen_features:
                raise ValueError("native_landmark_duplicate_observation")
            views.append(view)
            seen_features.add((image_id, fused))
            original = int(inverses[view][fused])
            if fused < row["videoRows"] or original < 0:
                reason = "video_or_ambiguous_source_row"
                continue
            pixel = pixels[original]
            x, y = np.floor(pixel + 0.5).astype(int)
            if not 0 <= x < SIZE[0] or not 0 <= y < SIZE[1] or mask[y, x] != 255:
                reason = "outside_capture_world_mask"
                continue
            matrix = matrices[view]
            local = matrix[:, :3] @ xyz + matrix[:, 3]
            projected = K @ local
            if local[2] <= 1e-5 or not np.isfinite(projected).all():
                reason = "nonpositive_depth"
                continue
            error = float(np.linalg.norm(projected[:2] / projected[2] - pixel))
            if error > 3.0:
                reason = "reprojection_over_3px"
                continue
            descriptor = desc[original].astype(np.float32) / 512.0
            norm = float(np.linalg.norm(descriptor))
            if not norm > 0:
                reason = "zero_descriptor"
                continue
            descriptor /= norm
            samples.append(descriptor)
            center = -matrix[:, :3].T @ matrix[:, 3]
            ray = xyz - center
            ray /= max(float(np.linalg.norm(ray)), 1e-12)
            rays.append(ray)
            measurements.append(
                dict(
                    view=view,
                    native_image_id=image_id,
                    fused_row=fused,
                    sift_image_id=row["siftImageId"],
                    sift_row=original,
                    reprojection_px=error,
                )
            )
        if reason is not None or len(views) < 3 or len(samples) != len(views):
            rejected[reason or "fewer_than_3_sift_views"] += 1
            continue
        rays = np.asarray(rays)
        if np.min(rays @ rays.T) > np.cos(np.deg2rad(1.0)):
            rejected["parallax_under_1_degree"] += 1
            continue
        samples = np.asarray(samples)
        distances = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * np.clip(samples @ samples.T, -1.0, 1.0)))
        medoid = int(np.argmin(distances.sum(axis=1)))
        if float(distances[medoid].max()) > 0.7:
            rejected["descriptor_inconsistency"] += 1
            continue
        candidates.append(
            (len(views), tuple(float(v) for v in xyz), samples[medoid].copy(), tuple(sorted(views)))
        )
        ids.append(int(point_id))
        proofs.append(
            dict(
                point3D_id=str(int(point_id)),
                observations=measurements,
                descriptor_observation=measurements[medoid],
            )
        )
    check()
    if provenance is not None:
        if type(provenance) is not list or provenance:
            raise ValueError("native_landmark_provenance_destination")
        provenance.extend(proofs)
    return (
        candidates,
        dict(
            schema="sphere-native-landmark-build-v1",
            descriptor_family=FAMILY,
            export_version=EXPORT_VERSION,
            native_points=len(rec.points3D),
            accepted=len(candidates),
            rejected=dict(sorted(rejected.items())),
            source_rows=total_rows,
            feature_bytes=feature_bytes,
            source_mask_sha256=_hash(mask),
            row_fingerprints=row_fingerprints,
            native_xyz_preserved=True,
            point_ids_preserved=True,
            feature_association="exact_row_mapping_only",
            triangulation_performed=False,
            pixel_coordinates="colmap_xy_times_scale_minus_half_v1",
            seconds=time.monotonic() - began,
        ),
        ids,
    )
