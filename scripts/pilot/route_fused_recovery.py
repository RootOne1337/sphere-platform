"""One bounded CPU fused-observation/global-SfM candidate for a saved route.

Native VIDEO and SIFT observation namespaces stay explicit. No camera is copied
from a demonstration, no closure is forced, and a successful native exit alone
cannot replace the baseline. The candidate owns all writes and no source video
is copied. Geometry admission is distinct from runtime-map and driving admission.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import site
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_component_merge import COLMAP, COLMAP_SHA256, _child_affinity
from scripts.pilot.route_geometry_selection import candidate_rank
from scripts.pilot.route_owned_process import spawn_owned

ROOT = Path(__file__).resolve().parents[2]
MAX_VIEWS = 240
MAX_FEATURES = 1024
MAX_PAIRS = 1800
MAX_MATCHES = 2_000_000
MAX_BYTES = 384 * 1024**2
MAX_SECONDS = 360
PAIR_ID_BASE = 2147483647
TEMPORAL_LAGS = (1, 2, 3, 5, 8)
LOOP_MIN_SEPARATION = 16
LOOP_TOP_K = 2
COARSE_MIN_COSINE = 0.3


def experimental_enabled():
    """Internal opt-in until a real candidate passes geometry qualification."""
    return os.environ.get("SPHERE_EXPERIMENTAL_FUSED_RECOVERY") == "1"


def _hash(path, check=lambda: None):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024**2):
            check()
            result.update(chunk)
    return result.hexdigest()


def _regular(path, root, maximum):
    path, root = Path(path), Path(root)
    if (
        not path.resolve().is_relative_to(root.resolve())
        or not path.is_file()
        or not 0 < path.stat().st_size <= maximum
    ):
        raise ValueError("fused_source_file")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("fused_source_symlink")
        if part == root:
            break


def _source(job, prepared, selected, check):
    if type(selected) is not int or not 10 <= selected <= MAX_VIEWS:
        raise ValueError("fused_view_quota")
    manifest, index, database = (
        job / "input/manifest.json",
        prepared / "reconstruction-input.json",
        prepared / "database.db",
    )
    for path, maximum in ((manifest, 65536), (index, 1024**2), (database, MAX_BYTES)):
        _regular(path, job, maximum)
    source = json.loads(index.read_bytes())
    rows = source.get("images")
    if (
        source.get("source_manifest_sha256") != _hash(manifest, check)
        or not isinstance(rows, list)
        or len(rows) != selected
    ):
        raise ValueError("fused_source_binding")
    names, images, previous_index, previous_ticks = set(), [], -1, -1
    for row in rows:
        check()
        if not isinstance(row, dict):
            raise ValueError("fused_source_row")
        name = row.get("image")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"images/[0-9]{8}\.png", name)
            or name in names
        ):
            raise ValueError("fused_image_namespace")
        source_index, ticks = row.get("source_index"), row.get("relative_ticks_90k")
        if (
            type(source_index) is not int
            or type(ticks) is not int
            or source_index <= previous_index
            or ticks <= previous_ticks
        ):
            raise ValueError("fused_source_order")
        previous_index, previous_ticks = source_index, ticks
        names.add(name)
        image = prepared / name
        _regular(image, job, 8 * 1024**2)
        if _hash(image, check) != row.get("png_sha256"):
            raise ValueError("fused_source_image_changed")
        images.append(image)
        mask = prepared / "masks" / (Path(name).name + ".png")
        if mask.exists():
            _regular(mask, job, 8 * 1024**2)
            images.append(mask)
    protected = [manifest, index, database]
    if database.with_name(database.name + "-wal").is_file():
        protected.append(database.with_name(database.name + "-wal"))
    return rows, {
        path.relative_to(job).as_posix(): _hash(path, check) for path in [*protected, *images]
    }


def _mask_context(job, prepared, bindings, check):
    """Declare the actual supplied masks; their historical producer is unknown.

    The manifest hash binds the capture/profile declaration, not a claim that
    today's preset generated historical mask pixels. Effective detector masks
    are saved separately and include the deterministic footer exclusion.
    """
    manifest = json.loads((job / "input/manifest.json").read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("fused_source_profile")
    config = manifest.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("fused_source_profile")
    profile = config.get("profile") or {}
    if not isinstance(profile, dict):
        raise ValueError("fused_source_profile")
    return dict(
        schema="sphere-fused-detector-masks-v1",
        source_manifest_sha256=bindings["input/manifest.json"],
        reconstruction_input_sha256=bindings[
            (prepared / "reconstruction-input.json").relative_to(job).as_posix()
        ],
        declared_profile={
            "mode": profile.get("mode"),
            "hudProfile": profile.get("hudProfile"),
            "hud_hidden_declared": config.get("hud_hidden_declared"),
        },
        supplied_mask_producer="unknown_hash_bound_pixels",
        detector_footer_exclusion_y=0.975,
        producer_sources={
            str(path.relative_to(ROOT).as_posix()): _hash(path, check)
            for path in (
                Path(__file__),
                ROOT / "scripts/pilot/learned_route_features.py",
                ROOT / "scripts/pilot/route_masks.py",
                ROOT / "scripts/pilot/route_native_track_policy.py",
            )
        },
    )


def coarse_signature(gray):
    """Small appearance proposal only; a similarity score never becomes a pose."""
    import cv2 as cv
    import numpy as np

    small = cv.resize(gray, (32, 18), interpolation=cv.INTER_AREA).astype(np.float32)
    small -= small.mean()
    norm = float(np.linalg.norm(small))
    return small.reshape(-1) / max(norm, 1e-6)


def propose_pairs(signatures, *, top_k=LOOP_TOP_K, separation=LOOP_MIN_SEPARATION):
    import numpy as np

    values = np.asarray(signatures, dtype=np.float32)
    if values.ndim != 2 or not 10 <= len(values) <= MAX_VIEWS or not np.isfinite(values).all():
        raise ValueError("fused_coarse_features")
    if top_k != LOOP_TOP_K or separation != LOOP_MIN_SEPARATION:
        raise ValueError("fused_pair_policy")
    pairs = {
        (i, i + lag): "temporal"
        for i in range(len(values))
        for lag in TEMPORAL_LAGS
        if i + lag < len(values)
    }
    similarity = values @ values.T
    for i in range(len(values)):
        candidates = sorted(
            (j for j in range(len(values)) if abs(j - i) >= separation),
            key=lambda j: (-float(similarity[i, j]), j),
        )
        for j in candidates[:top_k]:
            if similarity[i, j] >= COARSE_MIN_COSINE:
                pairs.setdefault(tuple(sorted((i, j))), "appearance_loop_proposal")
    if len(pairs) > MAX_PAIRS:
        raise ValueError("fused_pair_quota")
    return [(a, b, kind) for (a, b), kind in sorted(pairs.items())]


def _ratio_matches(first, second):
    import cv2 as cv

    if len(first) < 2 or len(second) < 2:
        return []
    matcher = cv.BFMatcher(cv.NORM_L2)
    forward = matcher.knnMatch(first, second, k=2)
    reverse = matcher.knnMatch(second, first, k=2)
    accepted_reverse = {
        a.queryIdx: a.trainIdx
        for pair in reverse
        if len(pair) == 2
        for a, b in [pair]
        if a.distance < 0.75 * b.distance and a.distance <= 0.7
    }
    return [
        (a.queryIdx, a.trainIdx)
        for pair in forward
        if len(pair) == 2
        for a, b in [pair]
        if a.distance < 0.75 * b.distance
        and a.distance <= 0.7
        and accepted_reverse.get(a.trainIdx) == a.queryIdx
    ]


def verified_matches(xy_a, desc_a, xy_b, desc_b, *, holdout=False, diagnostics=None):
    """Actual measured pixels, mutual descriptor ratio then training-only F.

    Exact physical-coordinate duplicates are removed before the deterministic
    holdout split. Holdout correspondences never enter F fitting or mapping.
    """
    import cv2 as cv
    import numpy as np

    if any(
        not isinstance(xy, np.ndarray)
        or xy.ndim != 2
        or xy.shape[1] != 2
        or not np.isfinite(xy).all()
        or not isinstance(desc, np.ndarray)
        or desc.shape != (len(xy), 128)
        or not np.isfinite(desc).all()
        for xy, desc in ((xy_a, desc_a), (xy_b, desc_b))
    ):
        raise ValueError("fused_feature_layout")
    matches, seen_a, seen_b = [], set(), set()
    for a, b in _ratio_matches(desc_a, desc_b):
        if not 0 <= a < len(xy_a) or not 0 <= b < len(xy_b):
            raise ValueError("fused_match_index")
        ka, kb = xy_a[a].tobytes(), xy_b[b].tobytes()
        if ka not in seen_a and kb not in seen_b:
            matches.append((a, b))
            seen_a.add(ka)
            seen_b.add(kb)
    matched = np.asarray(matches, dtype="<u4").reshape(-1, 2)
    held = np.arange(len(matched)) % 5 == 0 if holdout else np.zeros(len(matched), dtype=bool)
    train = matched[~held]
    if len(train) < 24:
        return np.empty((0, 2), dtype="<u4"), matched[held]
    cv.setRNGSeed(17)
    try:
        fundamental, inliers = cv.findFundamentalMat(
            xy_a[train[:, 0]] - 0.5,
            xy_b[train[:, 1]] - 0.5,
            method=cv.USAC_MAGSAC,
            ransacReprojThreshold=2.0,
            confidence=0.999,
            maxIters=10000,
        )
    except cv.error:
        # USAC can throw instead of returning no model for a degenerate pair.
        # That pair supplies zero constraints, without a threshold fallback.
        if diagnostics is not None:
            diagnostics["fundamental_model_error"] = (
                diagnostics.get("fundamental_model_error", 0) + 1
            )
        return np.empty((0, 2), dtype="<u4"), matched[held]
    if (
        fundamental is None
        or np.asarray(fundamental).shape != (3, 3)
        or not np.isfinite(fundamental).all()
        or np.linalg.matrix_rank(fundamental) != 2
        or inliers is None
        or inliers.size != len(train)
        or not np.isfinite(inliers).all()
        or not np.isin(inliers, (0, 1)).all()
    ):
        if diagnostics is not None:
            diagnostics["fundamental_model_invalid"] = (
                diagnostics.get("fundamental_model_invalid", 0) + 1
            )
        return np.empty((0, 2), dtype="<u4"), matched[held]
    accepted = train[inliers.reshape(-1).astype(bool)]
    if len(accepted) < 24 or len(accepted) / len(train) < 0.25:
        accepted = np.empty((0, 2), dtype="<u4")
    if len(accepted):
        for xy, indices in ((xy_a, accepted[:, 0]), (xy_b, accepted[:, 1])):
            span = np.maximum(np.ptp(xy, axis=0), 1.0)
            cells = np.floor((xy[indices] - xy.min(axis=0)) / span * 3.999).astype(int)
            if len(np.unique(cells[:, 1] * 4 + cells[:, 0])) < 4:
                accepted = np.empty((0, 2), dtype="<u4")
                break
    return accepted, matched[held]


def _pair_id(a, b):
    if not 0 < a < b < PAIR_ID_BASE:
        raise ValueError("fused_pair_identity")
    return PAIR_ID_BASE * a + b


def _decode_pair(value):
    return value // PAIR_ID_BASE, value % PAIR_ID_BASE


def _database_backup(source, output, *, check=lambda: None):
    if Path(output).exists() or Path(output).is_symlink():
        raise FileExistsError("fused_destination_exists")
    with (
        closing(
            sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)
        ) as original,
        closing(sqlite3.connect(output)) as target,
    ):
        original.backup(target, pages=256, progress=lambda *_args: check(), sleep=0.01)
    _seal_database(output)


def _seal_database(path):
    """Close/checkpoint an owned DB before hashing only its main-file bytes.

    sqlite3.Connection's transaction context is not a lifetime context. Every
    helper closes its handles explicitly; no later GC/worker exit may silently
    move unbound WAL bytes into an already sealed descriptor database.
    """
    with closing(sqlite3.connect(path, timeout=0.1)) as database:
        busy, *_counts = database.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if busy:
            raise ValueError("fused_database_not_sealed")
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("fused_database_not_sealed")


def _native_database_boundary(folder, label, check):
    """Record a closed/checkpointed main-file boundary before native handoff."""
    database = folder / "database.db"
    _seal_database(database)
    check()
    path = folder / "database-boundaries.json"
    report = (
        json.loads(path.read_bytes())
        if path.is_file()
        else dict(schema="sphere-fused-database-boundaries-v1", boundaries=[])
    )
    if len(report["boundaries"]) >= 8:
        raise ValueError("fused_database_boundary_quota")
    wal = Path(str(database) + "-wal")
    report["boundaries"].append(
        dict(
            stage=label,
            main_sha256=_hash(database, check),
            main_bytes=database.stat().st_size,
            wal_bytes=wal.stat().st_size if wal.exists() else 0,
            owned_sqlite_handles_explicitly_closed=True,
            pending_wal_checkpointed=True,
        )
    )
    write_json(path, report)


def _build_sift(prepared, source_database, output, rows, check, progress):
    import cv2 as cv
    import numpy as np

    from scripts.pilot.learned_route_features import extract_masked_sift

    cv.setNumThreads(2)
    database, features = output / "sift.db", output / "sift-features"
    features.mkdir()
    masks = output / "detector-masks"
    masks.mkdir()
    mask_records = []
    _database_backup(source_database, database, check=check)
    values, signatures = {}, []
    with closing(sqlite3.connect(database)) as db:
        db.executescript(
            "DELETE FROM matches; DELETE FROM two_view_geometries; DELETE FROM descriptors; DELETE FROM keypoints;"
        )
        identities = {
            name: identity for identity, name in db.execute("SELECT image_id,name FROM images")
        }
        if set(identities) != {Path(row["image"]).name for row in rows}:
            raise ValueError("fused_image_namespace")
        for n, row in enumerate(rows):
            check()
            progress("features", n, len(rows))
            name = Path(row["image"]).name
            gray = cv.imread(str(prepared / row["image"]), cv.IMREAD_GRAYSCALE)
            if gray is None:
                raise ValueError("fused_image_decode")
            path = prepared / "masks" / (name + ".png")
            mask = (
                cv.imread(str(path), cv.IMREAD_GRAYSCALE)
                if path.is_file()
                else np.full_like(gray, 255)
            )
            if mask is None or mask.shape != gray.shape:
                raise ValueError("fused_mask_invalid")
            mask[int(gray.shape[0] * 0.975) :] = 0
            mask_file = masks / name
            if not cv.imwrite(str(mask_file), mask):
                raise OSError("fused_mask_write_failed")
            mask_records.append(
                dict(
                    image=name,
                    supplied_mask_sha256=_hash(path, check) if path.is_file() else None,
                    effective_mask=dict(
                        path=mask_file.relative_to(output).as_posix(),
                        sha256=_hash(mask_file, check),
                    ),
                    width=int(gray.shape[1]),
                    height=int(gray.shape[0]),
                )
            )
            keys, desc = extract_masked_sift(gray, mask, MAX_FEATURES)
            if desc is None or len(keys) < 24:
                raise ValueError("fused_sift_support")
            xy = np.asarray([point.pt for point in keys], dtype="<f4") + 0.5
            desc = desc.astype(np.float32)
            desc /= np.maximum(desc.sum(-1, keepdims=True), 1e-6)
            desc = np.sqrt(np.maximum(desc, 1e-6))
            desc /= np.maximum(np.linalg.norm(desc, axis=-1, keepdims=True), 1e-6)
            geometry = np.column_stack(
                [
                    xy,
                    np.asarray([point.size for point in keys], dtype="<f4"),
                    np.deg2rad(np.asarray([point.angle for point in keys], dtype="<f4")),
                ]
            ).astype("<f4")
            identity = identities[name]
            db.execute(
                "INSERT INTO keypoints(image_id,rows,cols,data)VALUES(?,?,4,?)",
                (identity, len(xy), geometry.tobytes()),
            )
            db.execute(
                # COLMAP 4.2 requires an explicit FeatureExtractorType. SIFT=0
                # is verified against the pinned pycolmap/native DB fixture.
                "INSERT INTO descriptors(image_id,type,rows,cols,data)VALUES(?,0,?,128,?)",
                (
                    identity,
                    len(xy),
                    np.clip(np.round(desc * 512), 0, 255).astype("uint8").tobytes(),
                ),
            )
            np.savez_compressed(features / f"{identity}.npz", keypoints=geometry, descriptors=desc)
            values[identity] = (xy, desc)
            signatures.append(coarse_signature(gray))
        db.commit()
        pairs, heldouts, count, rejections = [], [], 0, {}
        proposals = propose_pairs(signatures)
        for n, (a, b, kind) in enumerate(proposals):
            check()
            progress("matching", n, MAX_PAIRS)
            ia, ib = (
                identities[Path(rows[a]["image"]).name],
                identities[Path(rows[b]["image"]).name],
            )
            xy_a, desc_a = values[ia]
            xy_b, desc_b = values[ib]
            matches, held = verified_matches(
                xy_a, desc_a, xy_b, desc_b, holdout=kind != "temporal", diagnostics=rejections
            )
            if len(matches) == 0:
                continue
            if ia > ib:
                ia, ib = ib, ia
                matches = matches[:, ::-1]
                held = held[:, ::-1]
            count += len(matches)
            if count > MAX_MATCHES:
                raise ValueError("fused_match_quota")
            db.execute(
                "INSERT INTO matches(pair_id,rows,cols,data)VALUES(?,?,2,?)",
                (_pair_id(ia, ib), len(matches), matches.astype("<u4").tobytes()),
            )
            pairs.append(dict(first=ia, second=ib, kind=kind, matches=len(matches)))
            if len(held):
                heldouts.append(dict(first=ia, second=ib, rows=held.tolist()))
        db.commit()
    _seal_database(database)
    write_json(
        output / "sift-pairs.json",
        dict(
            pairs=pairs,
            heldout=heldouts,
            holdout_used_for_fit=False,
            matcher="opencv_rootsift_mutual_global2nn_075_then_train_F2px",
            max_features=MAX_FEATURES,
            proposed_pairs=len(proposals),
            verified_pairs=len(pairs),
            pair_rejections=rejections,
        ),
    )
    write_json(output / "detector-masks.json", dict(images=mask_records))
    return database, pairs, heldouts


def fuse_databases(video_path, sift_path, output, *, image_bindings=None, check=lambda: None):
    """Fuse explicit measured row namespaces; never alias VID and SIFT rows."""
    import numpy as np

    _database_backup(video_path, output / "database.db", check=check)
    with (
        closing(
            sqlite3.connect(Path(video_path).resolve().as_uri() + "?mode=ro", uri=True)
        ) as video,
        closing(sqlite3.connect(Path(sift_path).resolve().as_uri() + "?mode=ro", uri=True)) as sift,
        closing(sqlite3.connect(output / "database.db")) as fused,
    ):
        cameras = video.execute("SELECT * FROM cameras").fetchall()
        if len(cameras) != 1 or cameras != sift.execute("SELECT * FROM cameras").fetchall():
            raise ValueError("fused_camera_namespace")
        video_images = dict(video.execute("SELECT image_id,name FROM images"))
        sift_images = dict(sift.execute("SELECT image_id,name FROM images"))
        by_name = {name: identity for identity, name in video_images.items()}
        if set(by_name) != set(sift_images.values()) or len(by_name) != len(video_images):
            raise ValueError("fused_image_namespace")
        ids, remaps, namespace, video_counts = {}, {}, [], {}
        fused.executescript(
            "DELETE FROM matches; DELETE FROM two_view_geometries; DELETE FROM descriptors;"
        )
        for identity, name in sorted(sift_images.items()):
            check()
            target = by_name[name]
            ids[identity] = target
            nv, vc, vb = video.execute(
                "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (target,)
            ).fetchone()
            ns, sc, sb = sift.execute(
                "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (identity,)
            ).fetchone()
            if vc != 4 or sc != 4 or not 0 < nv <= 8192 or not 0 < ns <= MAX_FEATURES:
                raise ValueError("fused_keypoint_layout")
            video_counts[target] = nv
            v, s = np.frombuffer(vb, "<f4").reshape(nv, 4), np.frombuffer(sb, "<f4").reshape(ns, 4)
            if not np.isfinite(v).all() or not np.isfinite(s).all():
                raise ValueError("fused_nonfinite_keypoints")
            unique, selected, remap = {}, [], np.empty(ns, dtype="<u4")
            for i, xy in enumerate(s[:, :2]):
                key = xy.tobytes()
                if key not in unique:
                    unique[key] = nv + len(selected)
                    selected.append(i)
                remap[i] = unique[key]
            combined = np.concatenate([v, s[selected]]).astype("<f4")
            if combined[:nv].tobytes() != vb or not np.array_equal(combined[remap, :2], s[:, :2]):
                raise ValueError("fused_row_remapping")
            fused.execute(
                "UPDATE keypoints SET rows=?,cols=4,data=? WHERE image_id=?",
                (len(combined), combined.tobytes(), target),
            )
            remaps[identity] = remap
            namespace.append(
                dict(
                    name=name,
                    videoImageId=target,
                    siftImageId=identity,
                    videoRows=nv,
                    siftRows=ns,
                    fusedRows=len(combined),
                    exactSiftAliases=ns - len(selected),
                    videoKeypointSHA=hashlib.sha256(vb).hexdigest(),
                    siftKeypointSHA=hashlib.sha256(sb).hexdigest(),
                    fusedKeypointSHA=hashlib.sha256(combined.tobytes()).hexdigest(),
                    sourcePngSHA=(image_bindings or {}).get(name),
                )
            )
        pairs, count = {}, 0
        for family, source in (("video", video), ("sift", sift)):
            for identity, nr, nc, blob in source.execute(
                "SELECT pair_id,rows,cols,data FROM matches"
            ):
                check()
                if nr == 0:
                    continue
                if nc != 2 or nr > MAX_FEATURES * 8 or blob is None or len(blob) != nr * 8:
                    raise ValueError("fused_match_layout")
                a, b = _decode_pair(identity)
                matches = np.frombuffer(blob, "<u4").reshape(nr, 2).copy()
                if family == "video" and (
                    a not in video_counts
                    or b not in video_counts
                    or matches[:, 0].max() >= video_counts[a]
                    or matches[:, 1].max() >= video_counts[b]
                ):
                    raise ValueError("fused_match_index")
                if family == "sift":
                    if (
                        a not in remaps
                        or b not in remaps
                        or matches[:, 0].max() >= len(remaps[a])
                        or matches[:, 1].max() >= len(remaps[b])
                    ):
                        raise ValueError("fused_match_index")
                    matches = np.column_stack([remaps[a][matches[:, 0]], remaps[b][matches[:, 1]]])
                    a, b = ids[a], ids[b]
                    if a > b:
                        a, b = b, a
                        matches = matches[:, ::-1]
                pairs.setdefault(_pair_id(a, b), []).append(matches)
        if len(pairs) > MAX_PAIRS:
            raise ValueError("fused_pair_quota")
        for identity, chunks in sorted(pairs.items()):
            matches = np.unique(np.concatenate(chunks), axis=0).astype("<u4")
            count += len(matches)
            if count > MAX_MATCHES:
                raise ValueError("fused_match_quota")
            fused.execute(
                "INSERT INTO matches(pair_id,rows,cols,data)VALUES(?,?,2,?)",
                (identity, len(matches), matches.tobytes()),
            )
        fused.commit()
    _seal_database(output / "database.db")
    np.savez_compressed(
        output / "row-remapping.npz", **{f"sift_{i}": value for i, value in remaps.items()}
    )
    report = dict(
        schema="sphere-fused-route-namespace-v1",
        images=namespace,
        pairs=len(pairs),
        matches=count,
        video_prefix_preserved=True,
        video_and_sift_distinct=True,
        source_video_database_sha256=_hash(video_path, check),
        source_sift_database_sha256=_hash(sift_path, check),
        row_remapping_sha256=_hash(output / "row-remapping.npz", check),
        sift_descriptors="quantized_rootsift_round512_uint8",
        full_float_features="sift-features/{siftImageId}.npz",
        execution_qualified=False,
    )
    write_json(output / "namespace.json", report)
    return report


def _process_bytes(process):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("faults", wintypes.DWORD),
                *[
                    (name, ctypes.c_size_t)
                    for name in (
                        "peakWorkingSet",
                        "workingSet",
                        "peakPaged",
                        "paged",
                        "peakNonpaged",
                        "nonpaged",
                        "pagefile",
                        "peakPagefile",
                        "private",
                    )
                ],
            ]

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(
            int(process.process._handle), ctypes.byref(value), value.cb
        ):
            raise RuntimeError("fused_child_memory_unavailable")
        return max(value.workingSet, value.private)
    values = Path(f"/proc/{process.pid}/status").read_text().splitlines()
    return max(
        (int(line.split()[1]) * 1024 for line in values if line.startswith(("VmRSS:", "VmData:"))),
        default=0,
    )


def audit_heldouts(folder, heldouts, rec, *, check=lambda: None):
    """Score clean measured loop pairs without using their labels for fitting.

    VIDEO can contain an exact physical alias even though its row namespace is
    distinct. Exclude that alias from EVALUATION only, retaining training data.
    These are same-video checks, not independent position/arrival ground truth.
    """
    import numpy as np

    namespace = json.loads((folder / "namespace.json").read_bytes())
    images = {row["siftImageId"]: row for row in namespace["images"]}
    mapping = np.load(folder / "row-remapping.npz", allow_pickle=False)
    reports, registered = [], set(rec.reg_image_ids())
    try:
        with closing(
            sqlite3.connect((folder / "database.db").resolve().as_uri() + "?mode=ro", uri=True)
        ) as db:
            for heldout in heldouts:
                check()
                a, b = heldout["first"], heldout["second"]
                ia, ib = images[a]["videoImageId"], images[b]["videoImageId"]
                rows_a, cols_a, raw_a = db.execute(
                    "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (ia,)
                ).fetchone()
                rows_b, cols_b, raw_b = db.execute(
                    "SELECT rows,cols,data FROM keypoints WHERE image_id=?", (ib,)
                ).fetchone()
                xy_a = np.frombuffer(raw_a, "<f4").reshape(rows_a, cols_a)[:, :2]
                xy_b = np.frombuffer(raw_b, "<f4").reshape(rows_b, cols_b)[:, :2]
                old = np.asarray(heldout["rows"], dtype=int).reshape(-1, 2)
                pairs = np.column_stack(
                    [mapping[f"sift_{a}"][old[:, 0]], mapping[f"sift_{b}"][old[:, 1]]]
                )

                def key(u, v):
                    return xy_a[u].tobytes() + xy_b[v].tobytes()

                found = db.execute(
                    "SELECT rows,data FROM matches WHERE pair_id=?",
                    (_pair_id(min(ia, ib), max(ia, ib)),),
                ).fetchone()
                train = (
                    np.frombuffer(found[1], "<u4").reshape(found[0], 2)
                    if found
                    else np.empty((0, 2), dtype=int)
                )
                if ia > ib:
                    train = train[:, ::-1]
                training = {key(u, v) for u, v in train}
                seen, clean, aliases = set(), [], 0
                for u, v in pairs:
                    identity = key(u, v)
                    if identity in training or identity in seen:
                        aliases += 1
                    else:
                        clean.append((u, v))
                        seen.add(identity)
                item = dict(
                    first=ia,
                    second=ib,
                    proposed=len(pairs),
                    physical_aliases_excluded=aliases,
                    clean=len(clean),
                    cameras_observed=ia in registered and ib in registered,
                    sampson_px=None,
                )
                if clean and item["cameras_observed"]:
                    first, second = rec.images[ia], rec.images[ib]
                    ma, mb = (
                        np.asarray(first.cam_from_world().matrix()),
                        np.asarray(second.cam_from_world().matrix()),
                    )
                    ka = np.asarray(rec.cameras[first.camera_id].calibration_matrix()).copy()
                    kb = np.asarray(rec.cameras[second.camera_id].calibration_matrix()).copy()
                    ka[:2, 2] -= 0.5
                    kb[:2, 2] -= 0.5
                    relative = mb[:, :3] @ ma[:, :3].T
                    translation = mb[:, 3] - relative @ ma[:, 3]
                    x, y, z = translation
                    cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
                    f = np.linalg.inv(kb).T @ cross @ relative @ np.linalg.inv(ka)
                    pairs_clean = np.asarray(clean)
                    left = np.column_stack([xy_a[pairs_clean[:, 0]] - 0.5, np.ones(len(clean))])
                    right = np.column_stack([xy_b[pairs_clean[:, 1]] - 0.5, np.ones(len(clean))])
                    fl, fr = left @ f.T, right @ f
                    denominator = (fl[:, :2] ** 2).sum(1) + (fr[:, :2] ** 2).sum(1)
                    valid = denominator > 1e-20
                    errors = np.sqrt(
                        (np.sum(right[valid] * fl[valid], axis=1) ** 2) / denominator[valid]
                    )
                    if len(errors) and np.isfinite(errors).all():
                        item["sampson_px"] = dict(
                            count=len(errors),
                            median=float(np.median(errors)),
                            p95=float(np.percentile(errors, 95)),
                            maximum=float(errors.max()),
                        )
                reports.append(item)
    finally:
        mapping.close()
    result = dict(
        schema="sphere-fused-physical-heldout-v1",
        pairs=reports,
        fit_used_heldout=False,
        physical_aliases_removed_from_evaluation_only=True,
        independent_gameplay=False,
        admission_effect="none",
    )
    write_json(folder / "heldout-audit.json", result)
    return result


def run_native(arguments, output, label, maximum_seconds, check):
    """Own the native process tree before resume; enforce deadline/CPU/memory."""
    began, peak = time.monotonic(), 0
    log_path = output / (label + ".log")
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        if os.name == "nt"
        else 0
    )
    process, failure = None, None
    try:
        with log_path.open("xb") as log:
            process = spawn_owned(
                [str(value) for value in arguments],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
            try:
                _child_affinity(process.pid)
                while process.poll() is None:
                    check()
                    try:
                        peak = max(peak, _process_bytes(process))
                    except (OSError, RuntimeError):
                        if process.poll() is not None:
                            break
                        raise
                    if peak > 1536 * 1024**2:
                        raise RuntimeError("fused_child_memory_quota")
                    if time.monotonic() - began > maximum_seconds:
                        raise RuntimeError("fused_native_timeout")
                    if log_path.stat().st_size > 4 * 1024**2:
                        raise RuntimeError("fused_log_quota")
                    time.sleep(0.1)
                check()
                if process.returncode != 0:
                    raise RuntimeError("fused_native_failed")
            finally:
                if process.poll() is None:
                    process.stop()
                process.close()
                process.wait(timeout=10)
    except Exception as error:
        failure = error
    receipt = dict(
        command=[str(v) for v in arguments],
        maximum_seconds=maximum_seconds,
        seconds=time.monotonic() - began,
        exit_code=process.returncode if process else None,
        ownership=process.ownership if process else None,
        status="completed" if failure is None else "failed",
        reason=str(failure) if failure else None,
        cpu_affinity_limit=2,
        peak_sampled_process_bytes=peak,
        memory_sampling_interval_seconds=0.1,
        log_sha256=_hash(log_path) if log_path.exists() else None,
        execution_qualified=False,
    )
    write_json(output / (label + "-receipt.json"), receipt)
    if failure is not None:
        raise failure
    return receipt


def recover_fused(
    job,
    prepared,
    baseline,
    selected,
    source_start,
    source_end,
    check,
    progress,
    *,
    assessment_check=None,
    native_runner=None,
):
    """Return baseline on one inconclusive candidate; cancellation/resources abort.

    Nothing is published by this function. The caller seals its chosen model
    through the common sparse receipt and independently prepares runtime maps.
    """
    job, prepared = Path(job), Path(prepared)
    folder = prepared / "fused-recovery"
    report = dict(
        schema="sphere-fused-route-recovery-v1",
        enabled=True,
        attempted=True,
        accepted=False,
        execution_qualified=False,
        source_modified=None,
        poses_manually_edited=False,
        closure_forced=False,
        network_downloads=False,
        physical_actions=0,
        matcher="opencv_rootsift_mutual_global2nn_075_then_train_F2px",
    )
    if folder.exists() or folder.is_symlink():
        return baseline, dict(report, attempted=False, reason="fused_existing_intent")
    rows, bindings = _source(job, prepared, selected, check)
    mask_context = _mask_context(job, prepared, bindings, check)
    folder.mkdir()
    write_json(
        folder / "intent.json",
        dict(
            report,
            source_bindings=bindings,
            detector_mask_context=mask_context,
            selected_views=selected,
            maximum_seconds=MAX_SECONDS,
            max_workspace_bytes=MAX_BYTES,
            native_global_seconds=150,
            fixed_k_ba_seconds=60,
        ),
    )
    began, last_size_check = time.monotonic(), None
    runner = run_native if native_runner is None else native_runner

    def bounded():
        nonlocal last_size_check
        check()
        if time.monotonic() - began > MAX_SECONDS:
            raise RuntimeError("fused_total_timeout")
        if last_size_check is None or time.monotonic() - last_size_check >= 1.0:
            if sum(path.stat().st_size for path in folder.rglob("*") if path.is_file()) > MAX_BYTES:
                raise RuntimeError("fused_workspace_quota")
            last_size_check = time.monotonic()

    try:
        import pycolmap as p

        from scripts.pilot.reconstruct_route import model_assessment
        from scripts.pilot.route_native_track_policy import (
            audit_native_model,
            filter_whole_tracks,
            measurement_signature,
        )

        if (
            p.__version__ != "4.2.1"
            or not COLMAP.is_file()
            or _hash(COLMAP, bounded) != COLMAP_SHA256
        ):
            raise RuntimeError("fused_native_unavailable")
        sift, pairs, heldouts = _build_sift(
            prepared, prepared / "database.db", folder, rows, bounded, progress
        )
        namespace = fuse_databases(
            prepared / "database.db",
            sift,
            folder,
            image_bindings={Path(row["image"]).name: row["png_sha256"] for row in rows},
            check=bounded,
        )
        names = {row["videoImageId"]: row["name"] for row in namespace["images"]}
        with closing(sqlite3.connect(folder / "database.db")) as database:
            pair_names = [
                _decode_pair(value) for (value,) in database.execute("SELECT pair_id FROM matches")
            ]
        pair_file = folder / "pairs.txt"
        pair_file.write_text(
            "".join(names[a] + " " + names[b] + "\n" for a, b in pair_names), encoding="ascii"
        )
        progress("matching", len(pairs), len(pairs))
        # The native verifier is executed in the same owned deadline process as
        # all other uninterruptible native stages, not inside the API thread.
        base_python = Path(getattr(sys, "_base_executable", sys.executable))
        site_paths = list(
            dict.fromkeys(
                [
                    str(ROOT),
                    *site.getsitepackages(),
                    *(value for value in sys.path if value and Path(value).name == "site-packages"),
                ]
            )
        )
        bootstrap = (
            "import sys;sys.path[:0]="
            + repr(site_paths)
            + ";from scripts.pilot.route_native_track_policy import verify;verify(sys.argv[1],sys.argv[2])"
        )
        _native_database_boundary(folder, "before_verify", bounded)
        runner(
            [base_python, "-c", bootstrap, folder / "database.db", pair_file],
            folder,
            "verify",
            45,
            bounded,
        )
        progress("cameras", 0, selected)
        _native_database_boundary(folder, "before_calibrate", bounded)
        runner(
            [
                COLMAP,
                "view_graph_calibrator",
                "--database_path",
                folder / "database.db",
                "--default_random_seed",
                "17",
                "--log_target",
                "stdout",
            ],
            folder,
            "calibrate",
            45,
            bounded,
        )
        models = folder / "models"
        models.mkdir()
        _native_database_boundary(folder, "before_global_map", bounded)
        runner(
            [
                COLMAP,
                "global_mapper",
                "--database_path",
                folder / "database.db",
                "--image_path",
                prepared / "images",
                "--output_path",
                models,
                "--default_random_seed",
                "17",
                "--log_target",
                "stdout",
                "--GlobalMapper.num_threads",
                "2",
                "--GlobalMapper.random_seed",
                "17",
                "--GlobalMapper.gp_use_gpu",
                "0",
                "--GlobalMapper.ba_ceres_use_gpu",
                "0",
                "--GlobalMapper.refine_sensor_from_rig",
                "0",
                "--GlobalMapper.track_intra_image_consistency_threshold",
                "1.0",
                "--GlobalMapper.tri_complete_max_reproj_error",
                "1.0",
                "--GlobalMapper.tri_merge_max_reproj_error",
                "1.0",
            ],
            folder,
            "global-map",
            150,
            bounded,
        )
        _native_database_boundary(folder, "after_global_map", bounded)
        candidates = []
        for path in sorted(models.iterdir()):
            bounded()
            if path.is_dir() and (path / "cameras.bin").is_file():
                rec = p.Reconstruction(path)
                _, assessment = model_assessment(
                    rec, prepared, selected, source_start, source_end, check=bounded
                )
                candidates.append((rec, assessment, path))
        if not candidates:
            raise RuntimeError("fused_no_global_model")
        rec, _, _ = max(candidates, key=lambda row: candidate_rank(row[1]))
        before = filter_whole_tracks(rec, check=bounded)
        if len(rec.points3D) < 300:
            raise ValueError("native_track_points_insufficient")
        camera_signature = measurement_signature(rec, check=bounded)["cameras"]
        filtered = folder / "filtered-model"
        filtered.mkdir()
        rec.write(filtered)
        # Base interpreter avoids measuring only a venv launcher while its
        # actual numerical worker is a different, unmeasured process.
        bootstrap = (
            "import sys;sys.path[:0]="
            + repr(site_paths)
            + ";from scripts.pilot.route_native_track_policy import bundle_adjust;bundle_adjust(sys.argv[1],sys.argv[2])"
        )
        runner(
            [base_python, "-c", bootstrap, filtered, folder / "ba-model"],
            folder,
            "fixed-k-ba",
            60,
            bounded,
        )
        rec = p.Reconstruction(folder / "ba-model")
        if measurement_signature(rec, check=bounded)["cameras"] != camera_signature:
            raise ValueError("native_track_ba_changed_intrinsics")
        after = filter_whole_tracks(rec, check=bounded)
        rec.update_point_3d_errors()
        audit = audit_native_model(rec, check=bounded)
        heldout_report = audit_heldouts(folder, heldouts, rec, check=bounded)
        geometry, assessment = model_assessment(
            rec, prepared, selected, source_start, source_end, check=bounded
        )
        base_assessment = (
            model_assessment(baseline, prepared, selected, source_start, source_end, check=bounded)[
                1
            ]
            if baseline is not None
            else None
        )
        target = folder / "model"
        target.mkdir()
        rec.write(target)
        write_json(folder / "geometry.json", geometry)
        write_json(folder / "assessment.json", assessment)
        write_json(
            folder / "track-policy.json", dict(before_ba=before, after_ba=after, audit=audit)
        )
        accepted = assessment["route_admissible"] and (
            base_assessment is None or candidate_rank(assessment) > candidate_rank(base_assessment)
        )
        report.update(
            accepted=accepted,
            reason="fused_candidate_selected"
            if accepted
            else "fused_candidate_not_better_or_incomplete",
            model="model",
            assessment=assessment,
            source_bindings=bindings,
            native_landmark_bundle=dict(
                model="model",
                namespace="namespace.json",
                row_mapping="row-remapping.npz",
                sift_database="sift.db",
                float_features="sift-features",
                mask_provenance="detector-masks.json",
            ),
            verified_pairs=len(pairs),
            heldout_pairs=len(heldouts),
            native_track_audit=audit,
            heldout_clean_matches=sum(row["clean"] for row in heldout_report["pairs"]),
            heldout_admission_effect="none",
        )
        report["source_manifest_sha256"] = _hash(job / "input/manifest.json", bounded)
        report["reconstruction_input_sha256"] = _hash(
            prepared / "reconstruction-input.json", bounded
        )
        report["model_sha256"] = {
            path.name: _hash(path, bounded) for path in sorted(target.glob("*.bin"))
        }
        _seal_database(folder / "sift.db")
        _native_database_boundary(folder, "final_bundle", bounded)
        if namespace.get("source_sift_database_sha256") != _hash(folder / "sift.db", bounded):
            raise ValueError("fused_descriptor_cache_changed")
        mask_provenance = json.loads((folder / "detector-masks.json").read_bytes())
        if len(mask_provenance.get("images", [])) != selected:
            raise ValueError("fused_mask_provenance")
        write_json(folder / "detector-masks.json", dict(mask_context, **mask_provenance))
        report["assets"] = {
            key: dict(path=path, sha256=_hash(folder / path, bounded))
            for key, path in (
                ("namespace", "namespace.json"),
                ("row_mapping", "row-remapping.npz"),
                ("sift_database", "sift.db"),
                ("fused_database", "database.db"),
                ("mask_provenance", "detector-masks.json"),
            )
        }
        chosen = rec if accepted else baseline
    except (
        ValueError,
        RuntimeError,
        OSError,
        ImportError,
        KeyError,
        TypeError,
        sqlite3.Error,
    ) as error:
        if str(error) in {"resource_guard", "cancelled", "route_resource_task_mismatch"}:
            report.update(accepted=False, reason=str(error), error_type=type(error).__name__)
            write_json(folder / "result.json", report)
            raise
        report.update(
            accepted=False,
            reason="fused_database_error"
            if isinstance(error, sqlite3.Error)
            else str(error)
            if str(error).startswith(("fused_", "native_track_", "component_merge_"))
            else "fused_candidate_failed",
            error_type=type(error).__name__,
        )
        chosen = baseline
    finally:
        report["seconds"] = time.monotonic() - began
    for name, expected in bindings.items():
        if _hash(job / name, check) != expected:
            report.update(source_modified=True, accepted=False, reason="fused_source_changed")
            write_json(folder / "result.json", report)
            raise RuntimeError("fused_source_changed")
    report["source_modified"] = False
    write_json(folder / "result.json", report)
    return chosen, report


def copy_frozen_model_if_current(job, prepared, rec, target, *, check=lambda: None, loader=None):
    """Preserve accepted native row identities in the canonical sparse model.

    Endpoint or later repairs must not acquire the old bundle's authority. If
    any native identity changed, the caller serializes its actual model and
    the native exporter will reject the stale bundle by exact model hashes.
    """
    from scripts.pilot.route_native_track_policy import native_identity_signature

    job, prepared, target = Path(job), Path(prepared), Path(target)
    folder = prepared / "fused-recovery"
    if not (folder / "result.json").is_file():
        return False
    try:
        _regular(folder / "result.json", job, 1024**2)
        report = json.loads((folder / "result.json").read_bytes())
        hashes = report.get("model_sha256")
        if (
            report.get("schema") != "sphere-fused-route-recovery-v1"
            or report.get("accepted") is not True
            or report.get("source_modified") is not False
            or report.get("model") != "model"
            or report.get("source_manifest_sha256") != _hash(job / "input/manifest.json", check)
            or report.get("reconstruction_input_sha256")
            != _hash(prepared / "reconstruction-input.json", check)
            or not isinstance(hashes, dict)
            or not {"cameras.bin", "images.bin", "points3D.bin"}.issubset(hashes)
            or not set(hashes).issubset(
                {"cameras.bin", "images.bin", "points3D.bin", "rigs.bin", "frames.bin"}
            )
            or not target.is_dir()
            or any(target.iterdir())
        ):
            return False
        for name, expected in hashes.items():
            path = folder / "model" / name
            _regular(path, job, MAX_BYTES)
            if _hash(path, check) != expected:
                return False
        if loader is None:
            import pycolmap as p

            loader = p.Reconstruction
        frozen = loader(folder / "model")
        if native_identity_signature(frozen, check=check) != native_identity_signature(
            rec, check=check
        ):
            return False
        check()
        for name, expected in hashes.items():
            shutil.copyfile(folder / "model" / name, target / name)
            if _hash(target / name, check) != expected:
                raise RuntimeError("fused_canonical_copy_changed")
        return True
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        return False
