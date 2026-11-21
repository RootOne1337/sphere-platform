"""Bounded same-recording image-route assets, independent of SfM and controls.

Two streaming decodes retain reference descriptors, not video frames. The broad
declared capture mask differs from the hand-made mask in the scooter experiment;
that experiment's accuracy is not claimed here. HUD/minimap fusion is disabled.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import platform
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.image_route_sequence import CausalSequenceBeam
from scripts.pilot.image_route_review import read_image_route_review
from scripts.pilot.route_masks import MODES, capture_exclusions

MIB = 1024**2
GIB = 1024**3
MAX_CACHE_BYTES = 128 * MIB
DISK_RESERVE_BYTES = 256 * MIB
ADMISSION_RAM_BYTES = ADMISSION_COMMIT_BYTES = 3 * GIB
RUNTIME_RAM_BYTES = RUNTIME_COMMIT_BYTES = 2 * GIB
MAX_COMMIT_FRACTION = 0.90
MAX_REVIEW_BYTES = 256 * 1024
MAX_PRODUCER_BYTES = 512 * 1024
MAX_FEATURES = 1024
MAX_SECONDS = 180.0
SOURCE_FILES = ("manifest.json", "frames.jsonl", "inputs.jsonl", "video.h264", "COMPLETE")
SCHEMA = "sphere-image-route-producer-v1"


@dataclass(frozen=True)
class Limits:
    references: int = 240
    queries: int = 1024
    cache_bytes: int = MAX_CACHE_BYTES
    seconds: float = MAX_SECONDS

    def __post_init__(self):
        if (
            type(self.references) is not int
            or not 2 <= self.references <= 256
            or type(self.queries) is not int
            or not 1 <= self.queries <= 1024
            or type(self.cache_bytes) is not int
            or not 0 < self.cache_bytes <= MAX_CACHE_BYTES
            or type(self.seconds) not in (int, float)
            or not 0 < self.seconds <= MAX_SECONDS
        ):
            raise ValueError("image_route_limits")


def resource_findings(snapshot, *, admission, cache_bytes=0, cache_limit=MAX_CACHE_BYTES):
    """Native counters only; keep physical RAM and Windows commit independent."""
    if not isinstance(snapshot, dict):
        return ["memory_measurement_unknown"]

    def integer(name):
        value = snapshot.get(name)
        return value if type(value) is int and value >= 0 else None

    findings = []
    ram, disk = integer("availableRamBytes"), integer("freeDiskBytes")
    if ram is None or ram < (ADMISSION_RAM_BYTES if admission else RUNTIME_RAM_BYTES):
        findings.append("ram_reserve")
    needed_disk = DISK_RESERVE_BYTES + max(0, cache_limit - cache_bytes)
    if disk is None or disk < needed_disk:
        findings.append("disk_reserve")
    if snapshot.get("system") == "Windows":
        used, limit = integer("committedBytes"), integer("commitLimitBytes")
        reserve = ADMISSION_COMMIT_BYTES if admission else RUNTIME_COMMIT_BYTES
        if used is None or limit is None or not 0 <= used < limit:
            findings.append("commit_unknown")
        elif limit - used < reserve or used / limit > MAX_COMMIT_FRACTION:
            findings.append("commit_reserve")
    elif snapshot.get("system") != "Linux":
        findings.append("memory_platform_unknown")
    return findings


def _measure(job):
    system = platform.system()
    value = dict(system=system, freeDiskBytes=shutil.disk_usage(job).free)
    if system == "Windows":
        from scripts.pilot.resource_guard import windows_memory

        value.update(windows_memory())
    elif system == "Linux":
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, text = line.split(":", 1)
            if key == "MemAvailable":
                value["availableRamBytes"] = int(text.split()[0]) * 1024
    return value


def _digest(path, check=lambda: None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("image_route_regular_file_required")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(MIB), b""):
            check()
            h.update(chunk)
    return h.hexdigest()


def pipeline_id():
    from motor_worker import image_route_sequence
    from scripts.pilot import route_masks

    h = hashlib.sha256()
    for path in (Path(__file__), Path(image_route_sequence.__file__), Path(route_masks.__file__)):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def uniform_rows(rows, count):
    """Nearest unique source rows to uniform media-PTS targets, both endpoints."""
    if not rows or type(count) is not int or count < 1:
        raise ValueError("image_route_sampling")
    count = min(count, len(rows))
    ticks = [row["relative_ticks_90k"] for row in rows]
    chosen = set()
    for at in range(count):
        target = ticks[0] if count == 1 else ticks[0] + (ticks[-1] - ticks[0]) * at / (count - 1)
        pos = bisect.bisect_left(ticks, target)
        # Quotas are <=1024 and metadata is <=36000 rows. This avoids retaining
        # image data and resolves sparse/uneven clocks without duplicate picks.
        left, right = pos - 1, pos
        while True:
            if left < 0:
                candidate = right
                right += 1
            elif right >= len(rows) or target - ticks[left] <= ticks[right] - target:
                candidate = left
                left -= 1
            else:
                candidate = right
                right += 1
            if candidate not in chosen:
                chosen.add(candidate)
                break
    return tuple(rows[i] for i in sorted(chosen))


def frame_plan(capture, limits):
    rows = capture.frames
    if len(rows) < 3:
        raise ValueError("image_route_insufficient_source_frames")
    duration = rows[-1]["relative_ticks_90k"] / 90000
    if not math.isfinite(duration) or not 0 < duration <= 601:
        raise ValueError("image_route_duration")
    count = min(limits.references, len(rows) - 1, max(2, math.ceil(duration / 0.25) + 1))
    references = uniform_rows(rows, count)
    selected = {row["index"] for row in references}
    queries = uniform_rows(
        tuple(row for row in rows if row["index"] not in selected), limits.queries
    )
    return references, queries


def _runtime():
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime

    initialize_route_cpu_runtime()
    import cv2
    import numpy

    return cv2, numpy


def _analysis(bgr, mask_mode, manifest, cv, np):
    height, width = bgr.shape[:2]
    scale = min(1.0, 960 / max(width, height))
    size = max(16, round(width * scale)), max(16, round(height * scale))
    gray = cv.resize(cv.cvtColor(bgr, cv.COLOR_BGR2GRAY), size, interpolation=cv.INTER_AREA)
    mask = np.full(gray.shape, 255, np.uint8)
    for a, b, c, d in capture_exclusions(mask_mode, manifest):
        cv.rectangle(
            mask, (int(a * size[0]), int(b * size[1])), (int(c * size[0]), int(d * size[1])), 0, -1
        )
    mask[int(mask.shape[0] * 0.975) :] = 0
    mask = cv.erode(mask, np.ones((17, 17), np.uint8), borderType=cv.BORDER_CONSTANT, borderValue=0)
    if not np.any(mask):
        raise ValueError("image_route_empty_feature_mask")
    return gray, mask


def _features(gray, mask, cv, np):
    detector = cv.SIFT_create(nfeatures=2048, contrastThreshold=0.0066667, edgeThreshold=10)
    kp, descriptors = detector.detectAndCompute(gray, mask)
    if descriptors is None:
        points, descriptors = np.empty((0, 2), np.float32), np.empty((0, 128), np.float32)
    else:
        keep = sorted(range(len(kp)), key=lambda i: (-kp[i].response, i))[:MAX_FEATURES]
        points = np.asarray([kp[i].pt for i in keep], np.float32)
        descriptors = descriptors[keep]
        descriptors = np.sqrt(
            descriptors / np.maximum(descriptors.sum(axis=1, keepdims=True), 1e-8)
        )
        descriptors /= np.maximum(np.linalg.norm(descriptors, axis=1, keepdims=True), 1e-8)
    small = cv.resize(gray, (85, 48), interpolation=cv.INTER_AREA).astype(np.float32) / 255.0
    allowed = cv.resize(mask, (85, 48), interpolation=cv.INTER_NEAREST) > 0
    if not allowed.any():
        raise ValueError("image_route_empty_coarse_mask")
    mean = float(small[allowed].mean())
    small = np.where(allowed, small, mean).astype(np.float32) - mean
    coarse = cv.dct(small)[:12, :16].ravel()[1:]
    coarse /= max(float(np.linalg.norm(coarse)), 1e-12)
    return points, descriptors.astype(np.float32), coarse


def _valid_features(features, shape, np):
    points, descriptors, coarse = features
    height, width = shape
    if (
        points.dtype != np.float32
        or points.ndim != 2
        or points.shape[1:] != (2,)
        or len(points) > MAX_FEATURES
        or descriptors.dtype != np.float32
        or descriptors.shape != (len(points), 128)
        or coarse.dtype != np.float32
        or coarse.shape != (191,)
        or not all(np.isfinite(v).all() for v in features)
        or (points < 0).any()
        or (points[:, 0] >= width).any()
        or (points[:, 1] >= height).any()
    ):
        raise ValueError("image_route_feature_contract")


def _verify(query, reference, shape, cv, np):
    qp, qd, _ = query
    rp, rd, _ = reference
    if len(qd) < 2 or len(rd) < 2:
        return 0.0
    pairs = cv.BFMatcher(cv.NORM_L2).knnMatch(qd, rd, k=2)
    unique: dict[int, Any] = {}  # OpenCV DMatch objects from an optional runtime import.
    for pair in pairs:
        if len(pair) != 2 or pair[0].distance >= 0.75 * pair[1].distance:
            continue
        match = pair[0]
        if match.trainIdx not in unique or match.distance < unique[match.trainIdx].distance:
            unique[match.trainIdx] = match
    good, query_positions, reference_positions = [], set(), set()
    for match in sorted(unique.values(), key=lambda m: m.distance):
        query_position = tuple(np.round(qp[match.queryIdx], 3))
        reference_position = tuple(np.round(rp[match.trainIdx], 3))
        if query_position not in query_positions and reference_position not in reference_positions:
            good.append(match)
            query_positions.add(query_position)
            reference_positions.add(reference_position)
    if len(good) < 20:
        return 0.0
    a = np.asarray([qp[m.queryIdx] for m in good], np.float32)
    b = np.asarray([rp[m.trainIdx] for m in good], np.float32)
    cv.setRNGSeed(17)
    matrix, mask = cv.findFundamentalMat(a, b, cv.FM_RANSAC, 1.5, 0.999, 2000)
    if (
        matrix is None
        or mask is None
        or matrix.shape != (3, 3)
        or not np.isfinite(matrix).all()
        or mask.size != len(good)
    ):
        return 0.0
    accepted = mask.ravel().astype(bool)
    n, fraction = int(accepted.sum()), float(accepted.mean())
    height, width = shape
    cells = np.floor(a[accepted] / [width, height] * 4).astype(int)
    occupied = len(np.unique(cells[:, 1] * 4 + cells[:, 0])) if n else 0
    return (
        min(n / 80.0, 1.0) * fraction * min(occupied / 5.6, 1.0)
        if n >= 20 and fraction >= 0.35 and occupied >= 4
        else 0.0
    )


def _json(path, value, maximum):
    body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > maximum:
        raise ValueError("image_route_output_quota")
    with path.open("xb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    return body


def _cleanup(folder, job):
    if (
        folder.parent.resolve() != job
        or not folder.name.startswith(".image-route-review-building-")
        or folder.is_symlink()
        or getattr(folder, "is_junction", lambda: False)()
    ):
        raise ValueError("image_route_cleanup_path")
    if folder.exists():
        shutil.rmtree(folder)


def _checked_npz(path, np):
    # Inspect shape/dtype *before* np.load can allocate from an untrusted NPY
    # header. A small compressed ZIP alone is not a memory bound.
    shapes = {}
    with zipfile.ZipFile(path) as archive:
        if (
            set(archive.namelist()) != {"points.npy", "descriptors.npy", "coarse.npy"}
            or len(archive.infolist()) != 3
        ):
            raise ValueError("image_route_index_arrays")
        for info in archive.infolist():
            if info.file_size > MIB:
                raise ValueError("image_route_index_array_quota")
            with archive.open(info) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(
                        stream, max_header_size=4096
                    )
                elif version == (2, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_2_0(
                        stream, max_header_size=4096
                    )
                else:
                    raise ValueError("image_route_index_array_version")
                if (
                    dtype != np.dtype("float32")
                    or fortran
                    or not isinstance(shape, tuple)
                    or any(type(v) is not int or not 0 <= v <= MAX_FEATURES for v in shape)
                    or stream.tell() + math.prod(shape) * dtype.itemsize != info.file_size
                ):
                    raise ValueError("image_route_index_array_header")
                shapes[info.filename] = shape
        count = shapes["points.npy"][0] if len(shapes["points.npy"]) == 2 else -1
        if (
            shapes["points.npy"] != (count, 2)
            or shapes["descriptors.npy"] != (count, 128)
            or shapes["coarse.npy"] != (191,)
        ):
            raise ValueError("image_route_index_array_shape")
    with np.load(path, allow_pickle=False) as data:
        return data["points"], data["descriptors"], data["coarse"]


def read_index(job, *, check=lambda: None):
    """Read bounded, hash-verified descriptor assets; never a pose/control map."""
    import numpy as np

    job = Path(job).absolute()
    review = json.loads(read_image_route_review(job))
    folder = job / "image-route-review"
    path = folder / "producer.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PRODUCER_BYTES:
        raise ValueError("image_route_index_receipt")
    metadata = json.loads(path.read_bytes())
    if (
        metadata.get("schema") != SCHEMA
        or metadata.get("pipeline_sha256") != pipeline_id()
        or metadata.get("source_hashes", {}).get("manifest.json")
        != review["source_manifest_sha256"]
        or metadata.get("review_sha256") != _digest(folder / "review.json")
        or metadata.get("execution_qualified") is not False
        or metadata.get("source_unchanged") is not True
        or type(metadata.get("references")) is not list
        or not 2 <= len(metadata["references"]) <= 256
    ):
        raise ValueError("image_route_index_binding")
    if metadata.get("source_hashes") != {
        name: _digest(job / "input" / name, check) for name in SOURCE_FILES
    }:
        raise ValueError("image_route_index_source_changed")
    values, total, ticks = [], 0, []
    shape = metadata.get("analysis_shape")
    if (
        type(shape) is not list
        or len(shape) != 2
        or any(type(v) is not int or not 16 <= v <= 960 for v in shape)
    ):
        raise ValueError("image_route_index_geometry")
    frames = {r["index"]: r for r in validate_browser(job / "input").frames}
    seen = set()
    for row in metadata["references"]:
        check()
        index = row.get("source_index")
        if (
            type(index) is not int
            or index in seen
            or index not in frames
            or row.get("ticks_90k") != frames[index]["relative_ticks_90k"]
            or row.get("source_access_unit_sha256") != frames[index]["sha256"]
            or row.get("path") != f"index/{index:08d}.npz"
        ):
            raise ValueError("image_route_index_source")
        seen.add(index)
        ticks.append(row["ticks_90k"])
        cache = folder / row["path"]
        if (
            cache.parent.is_symlink()
            or cache.is_symlink()
            or not cache.is_file()
            or getattr(cache.parent, "is_junction", lambda: False)()
            or not cache.resolve(strict=True).is_relative_to(folder.resolve(strict=True))
        ):
            raise ValueError("image_route_index_path")
        total += cache.stat().st_size
        if total > MAX_CACHE_BYTES or _digest(cache, check) != row.get("sha256"):
            raise ValueError("image_route_index_cache")
        features = _checked_npz(cache, np)
        _valid_features(features, shape, np)
        values.append(features)
    if ticks != review["reference_ticks_90k"] or total != metadata.get("cache_bytes"):
        raise ValueError("image_route_index_extent")
    return metadata, tuple(values)


def run(job, mask="game", *, check=None, progress=None, limits=Limits()):
    """Build once, or reuse a verified existing review without overwriting it.

    ``check()`` composes caller cancellation/resource checks. ``progress(dict)``
    receives bounded phase/frame/cache counters. Inputs/geometry/main job state
    are read-only. The only shared output is the final image-route-review dir.
    """
    if mask not in MODES or not isinstance(limits, Limits):
        raise ValueError("image_route_options")
    path = Path(job).absolute()
    if path.is_symlink() or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("image_route_job_path")
    job = path
    destination = job / "image-route-review"
    started = time.monotonic()
    cache_bytes = 0

    def checkpoint(admission=False):
        if (job / "CANCEL").exists() or (job / "image-route-workspace/CANCEL").exists():
            raise RuntimeError("cancelled")
        if time.monotonic() - started > limits.seconds:
            raise RuntimeError("image_route_timeout")
        if check is not None:
            check()
        try:
            findings = resource_findings(
                _measure(job),
                admission=admission,
                cache_bytes=cache_bytes,
                cache_limit=limits.cache_bytes,
            )
        except (OSError, ValueError):
            raise RuntimeError("image_route_resource_measurement") from None
        if findings:
            raise RuntimeError("image_route_resource_guard:" + ",".join(findings))

    def notify(phase, done, total):
        if progress is not None:
            progress(dict(phase=phase, completed=done, total=total, cache_bytes=cache_bytes))

    if os.path.lexists(destination):
        data = json.loads(read_image_route_review(job))
        index_available = (destination / "producer.json").is_file()
        if index_available:
            cache_bytes = limits.cache_bytes  # Reuse writes no additional cache.
            read_index(job, check=checkpoint)
        return dict(
            phase="ready",
            reused=True,
            references=len(data["reference_ticks_90k"]),
            samples=len(data["samples"]),
            index_available=index_available,
            execution_qualified=False,
        )
    checkpoint(admission=True)
    recipe_sha = pipeline_id()
    capture = validate_browser(job / "input")
    before = {name: _digest(job / "input" / name, checkpoint) for name in SOURCE_FILES}
    for name, raw in capture.originals.items():
        if before[name] != hashlib.sha256(raw).hexdigest():
            raise ValueError("image_route_source_changed")
    # Browser v1/v2 can seal compressed media through the SHA of every access
    # unit in the hashed frames.jsonl, without a manifest-wide video digest.
    # Both complete decoded_browser passes validate those units. Our own full
    # digest still binds the retained cache and detects source changes.
    video_entry = capture.manifest["files"]["video.h264"]
    if "sha256" in video_entry and before["video.h264"] != video_entry["sha256"]:
        raise ValueError("image_route_video_binding")
    references, queries = frame_plan(capture, limits)
    cv, np = _runtime()
    temporary = job / (".image-route-review-building-" + uuid.uuid4().hex)
    lock = job / ".image-route-review-builder.lock"
    lock.mkdir()  # One builder, including callers outside the jobs service.
    try:
        if os.path.lexists(destination):
            raise FileExistsError("image_route_output_already_exists")
        temporary.mkdir()
        (temporary / "index").mkdir()
        selected = {row["index"]: row for row in references}
        features, ref_hashes, cache_rows = {}, {}, []
        analysis_shape = None
        for count, (row, frame) in enumerate(decoded_browser(capture), 1):
            checkpoint()
            if row["index"] in selected:
                bgr = frame.to_ndarray(format="bgr24")
                if (
                    bgr.shape != (capture.geometry[1], capture.geometry[0], 3)
                    or bgr.dtype != np.uint8
                ):
                    raise ValueError("image_route_decoded_geometry")
                bgr_sha = hashlib.sha256(bgr.tobytes()).hexdigest()
                gray, allowed = _analysis(bgr, mask, capture.manifest, cv, np)
                analysis_shape = gray.shape
                value = _features(gray, allowed, cv, np)
                _valid_features(value, gray.shape, np)
                index = row["index"]
                features[index] = value
                ref_hashes[index] = bgr_sha
                name = f"index/{index:08d}.npz"
                cache = temporary / name
                np.savez_compressed(cache, points=value[0], descriptors=value[1], coarse=value[2])
                cache_bytes += cache.stat().st_size
                if cache_bytes > limits.cache_bytes:
                    raise RuntimeError("image_route_cache_quota")
                cache_rows.append(
                    dict(
                        source_index=index,
                        ticks_90k=row["relative_ticks_90k"],
                        source_access_unit_sha256=row["sha256"],
                        bgr_sha256=bgr_sha,
                        path=name,
                        sha256=_digest(cache, checkpoint),
                        features=len(value[0]),
                    )
                )
            if count % 32 == 0:
                notify("reference_index", count, len(capture.frames))
        if len(features) != len(references):
            raise ValueError("image_route_reference_decode_incomplete")
        checkpoint()
        notify("reference_index", len(capture.frames), len(capture.frames))
        ref_ticks = [row["relative_ticks_90k"] for row in references]
        ref_values = [features[row["index"]] for row in references]
        coarse = np.asarray([value[2] for value in ref_values], np.float32)
        beam = CausalSequenceBeam(tuple(t / 90000 for t in ref_ticks))
        selected_queries = {row["index"] for row in queries}
        samples, source_rows = [], []
        all_scores = np.zeros((len(queries), len(references)), np.float32)
        all_checked = np.zeros(all_scores.shape, bool)
        ref_rgb = set(ref_hashes.values())
        for count, (row, frame) in enumerate(decoded_browser(capture), 1):
            checkpoint()
            if row["index"] not in selected_queries:
                continue
            bgr = frame.to_ndarray(format="bgr24")
            if bgr.shape != (capture.geometry[1], capture.geometry[0], 3) or bgr.dtype != np.uint8:
                raise ValueError("image_route_decoded_geometry")
            bgr_sha = hashlib.sha256(bgr.tobytes()).hexdigest()
            scores = [0.0] * len(references)
            checked = [False] * len(references)
            if bgr_sha not in ref_rgb:
                gray, allowed = _analysis(bgr, mask, capture.manifest, cv, np)
                value = _features(gray, allowed, cv, np)
                _valid_features(value, gray.shape, np)
                eligible = [
                    i
                    for i, tick in enumerate(ref_ticks)
                    if abs(tick - row["relative_ticks_90k"]) > 13500
                ]
                ranked = sorted(
                    eligible, key=lambda i: (float(np.linalg.norm(coarse[i] - value[2])), i)
                )[:8]
                for i in ranked:
                    checkpoint()
                    checked[i] = True
                    scores[i] = float(_verify(value, ref_values[i], gray.shape, cv, np))
            tick = row["relative_ticks_90k"]
            evidence = beam.update(
                scores,
                checked=checked,
                source_sequence=row["index"],
                received_at=tick / 90000,
                now=tick / 90000,
                source_sha256=bgr_sha,
            )
            best = max(range(len(scores)), key=scores.__getitem__)
            samples.append(
                dict(
                    source_index=row["index"],
                    ticks_90k=tick,
                    raw_score=scores[best],
                    raw_reference_ticks_90k=ref_ticks[best] if scores[best] > 0 else None,
                    sequence_reference_ticks_90k=ref_ticks[evidence.index]
                    if evidence.index is not None
                    else None,
                    sequence_status=evidence.status,
                )
            )
            at = len(samples) - 1
            all_scores[at] = scores
            all_checked[at] = checked
            source_rows.append(
                dict(
                    source_index=row["index"],
                    ticks_90k=tick,
                    bgr_sha256=bgr_sha,
                    checked=sum(checked),
                    exact_reference_repeat=bgr_sha in ref_rgb,
                )
            )
            if len(samples) % 16 == 0:
                notify("queries", len(samples), len(queries))
        if len(samples) != len(queries):
            raise ValueError("image_route_query_decode_incomplete")
        checkpoint()
        notify("queries", len(samples), len(queries))
        after = {name: _digest(job / "input" / name, checkpoint) for name in SOURCE_FILES}
        if before != after or pipeline_id() != recipe_sha:
            raise ValueError("image_route_source_changed")
        review = dict(
            schema="sphere-image-route-review-v1",
            scope="OFFLINE_SAME_RECORDING",
            source_manifest_sha256=before["manifest.json"],
            position_confirmed=False,
            arrival_confirmed=False,
            execution_qualified=False,
            reference_ticks_90k=ref_ticks,
            samples=samples,
        )
        body = _json(temporary / "review.json", review, MAX_REVIEW_BYTES)
        receipt = dict(
            schema="sphere-image-route-review-receipt-v1",
            scope="DIAGNOSTIC_ONLY",
            execution_qualified=False,
            source_manifest_sha256=before["manifest.json"],
            review_sha256=hashlib.sha256(body).hexdigest(),
            frames_sha256=before["frames.jsonl"],
        )
        _json(temporary / "receipt.json", receipt, 4096)
        np.savez_compressed(temporary / "evidence.npz", scores=all_scores, checked=all_checked)
        producer = dict(
            schema=SCHEMA,
            pipeline_sha256=recipe_sha,
            source_hashes=before,
            source_video_binding="per_access_unit_decode_and_computed_aggregate",
            source_unchanged=True,
            review_sha256=receipt["review_sha256"],
            evidence_sha256=_digest(temporary / "evidence.npz", checkpoint),
            mask_mode=mask,
            exclusions=capture_exclusions(mask, capture.manifest),
            footer_fraction=0.025,
            mask_erosion_pixels=8,
            analysis_shape=analysis_shape,
            source_geometry=capture.geometry,
            keypoint_coordinates="opencv_pixel_centers_in_analysis_image",
            decoded_hash_format="bgr24_full_resolution_bytes",
            selection="uniform_source_pts_no_sfm",
            references=cache_rows,
            queries=source_rows,
            cache_bytes=cache_bytes,
            cache_limit_bytes=limits.cache_bytes,
            runtime=dict(opencv=cv.__version__, numpy=np.__version__),
            feature_settings=dict(
                detector="SIFT",
                detector_cap=2048,
                retained_limit_after_mask=1024,
                normalization="RootSIFT",
                coarse="DCT_85x48_12x16_without_DC",
                shortlist=8,
                near_reference_exclusion_ticks=13500,
            ),
            minimap_fusion=False,
            received_clock="synthetic_zero_latency_query_pts",
            elapsed_seconds=time.monotonic() - started,
            limit_seconds=limits.seconds,
            scope="OFFLINE_SAME_RECORDING",
            position_confirmed=False,
            arrival_confirmed=False,
            execution_qualified=False,
        )
        _json(temporary / "producer.json", producer, MAX_PRODUCER_BYTES)
        # Validate the exact existing HTTP contract against this source without
        # exposing a partial final directory. The reader uses job/input, so a
        # temporary validation job is unnecessary: all invariants are checked
        # above; final reader validation is repeated by the caller/API.
        checkpoint()
        if os.path.lexists(destination):
            raise FileExistsError("image_route_output_already_exists")
        temporary.rename(destination)
        return dict(
            phase="ready",
            reused=False,
            references=len(references),
            samples=len(samples),
            cache_bytes=cache_bytes,
            seconds=time.monotonic() - started,
            source_manifest_sha256=before["manifest.json"],
            execution_qualified=False,
        )
    finally:
        _cleanup(temporary, job)
        lock.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--mask", required=True, choices=MODES)
    args = parser.parse_args()
    try:
        result = run(args.job, args.mask, progress=lambda row: print(json.dumps(row), flush=True))
        print(json.dumps(result), flush=True)
    except Exception as error:
        print(
            json.dumps(dict(phase="failed", error=str(error)[:200], execution_qualified=False)),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
