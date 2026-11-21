"""Verify globally retrieved locations by matching RGB against mesh-rendered RGB and depth."""

import argparse
import base64
import hashlib
import json
import math
import time
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright
from scipy.spatial import cKDTree

from scripts.pilot.route_roma_runtime import RomaProcess, Runtime
from scripts.pilot.world_map_lab.bake_world_course import renderer
from scripts.pilot.world_map_lab.check_destination_district import lift
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator, features


def source_observation(page, pose, focal):
    jpg, packed = page.evaluate("p=>mapReferenceRGBD(p)", pose)
    bgr = cv2.imdecode(np.frombuffer(base64.b64decode(jpg), np.uint8), cv2.IMREAD_COLOR)
    depth = (
        np.frombuffer(base64.b64decode(packed), "<u2").reshape(SIZE[::-1]).astype(np.float32) / 128
    )
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    corners = cv2.goodFeaturesToTrack(gray, 3000, 0.002, 5)
    if corners is None:
        return None
    uv = corners[:, 0]
    x, y = uv.round().astype(int).T
    x = np.clip(x, 1, SIZE[0] - 2)
    y = np.clip(y, 1, SIZE[1] - 2)
    z = depth[y, x]
    change = np.maximum.reduce(
        [np.abs(depth[y + dy, x + dx] - z) for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]]
    )
    keep = (z > 1) & (z < 180) & (change < 0.12 + 0.02 * z)
    if keep.sum() < 48:
        return None
    rgb = cv2.cvtColor(cv2.resize(bgr, (960, 540)), cv2.COLOR_BGR2RGB)
    return (
        rgb,
        ((uv[keep] + 0.5) * 1.5 - 0.5).astype(np.float32),
        lift(uv[keep], z[keep], focal, pose),
    )


def consistent_views(rows):
    confirmed = []
    for a, b in combinations(rows, 2):
        first, second = a["pose"], b["pose"]
        angle = math.remainder(a["delta"] - b["delta"], 2 * math.pi)
        independent_angles = a["frame"] != b["frame"] and abs(angle) >= 0.32
        # When parked, two spatially separated source cameras can independently
        # constrain the same live view. Require tighter agreement for this case.
        stereo = (
            a["frame"] == b["frame"]
            and a["site"] >= 0
            and b["site"] >= 0
            and a["site"] != b["site"]
            and math.dist(a["sourceEye"], b["sourceEye"]) >= 8
            and min(first["supports"], second["supports"]) >= 60
        )
        if not independent_angles and not stereo:
            continue
        residual = math.remainder(first["heading"] - second["heading"] - angle, 2 * math.pi)
        if math.dist(first["eye"], second["eye"]) <= (0.45 if stereo else 1) and abs(
            residual
        ) <= math.radians(2 if stereo else 5):
            confirmed.extend((first, second))
    return confirmed


def write_tracking_atlas(path, images, anchors, rows, pose, focal, revision):
    """Only expose live appearance backed by measured 2D-to-source-mesh inliers."""
    detector = cv2.SIFT_create(nfeatures=2400, contrastThreshold=0.018)
    views, desc, xyz, ids, pixels, points, trace = [], [], [], [], [], [], []
    offsets = [0]
    for frame in sorted({r["frame"] for r in rows if r["pose"]}):
        choices = [
            (i, r)
            for i, r in enumerate(rows)
            if r["frame"] == frame and r["pose"] and math.dist(pose["eye"], r["pose"]["eye"]) <= 1
        ]
        if not choices:
            continue
        idx, row = max(choices, key=lambda item: item[1]["pose"]["supports"])
        uv, world = anchors[idx]["pixels"], anchors[idx]["world"]
        gray = cv2.resize(
            cv2.cvtColor(images[frame], cv2.COLOR_BGR2GRAY), SIZE, interpolation=cv2.INTER_AREA
        )
        keypoints, descriptors = features(gray, detector)
        distance, neighbor = cKDTree(uv).query(keypoints)
        keep = distance <= 1.7
        if keep.sum() < 10:
            continue
        ids.append(np.full(keep.sum(), len(views), np.int16))
        desc.append(descriptors[keep])
        xyz.append(world[neighbor[keep]])
        views.append(gray)
        pixels.append(uv)
        points.append(world)
        trace.append(row["pose"]["eye"])
        offsets.append(offsets[-1] + len(uv))
    if not views:
        return False
    meta = dict(
        source="source-map-grid",
        independentScenery=True,
        revision=revision,
        coverageRadius=16.0,
        visualTrace=trace,
        trainingViews=len(views),
        landmarks=sum(len(a) for a in xyz),
        width=SIZE[0],
        height=SIZE[1],
    )
    tmp = path.with_suffix(".partial")
    with tmp.open("wb") as f:
        np.savez_compressed(
            f,
            desc=np.concatenate(desc),
            xyz=np.concatenate(xyz),
            views=np.stack(views),
            viewIds=np.concatenate(ids),
            trackOffsets=offsets,
            trackPixels=np.concatenate(pixels),
            trackXYZ=np.concatenate(points),
            meta=json.dumps(meta),
            intrinsics=[focal, focal, 319.5, 179.5],
        )
    tmp.replace(path)
    return True


def run(args):
    source = json.loads(args.results.read_bytes())
    if source.get("frameDigests") != [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in args.frames
    ]:
        raise ValueError("query images or frame order differ from the retrieval")
    meta = json.loads(args.scene.read_bytes())
    if source["revision"] != meta["revision"]:
        raise ValueError("map revision mismatch")
    if args.output.exists():
        raise FileExistsError(args.output)
    images = [cv2.imread(str(file)) for file in args.frames]
    if not images or any(im is None for im in images):
        raise ValueError("missing live RGB")
    cv2.setNumThreads(2)
    worker = RomaProcess(
        Runtime(args.interpreter.resolve(strict=True), args.matcher.resolve(strict=True))
    )
    evidence = []
    confirmed = []
    anchors = {}
    try:
        while worker.status == "warming":
            worker.poll()
            time.sleep(0.025)
        if not worker.available:
            raise RuntimeError("GPU matcher unavailable")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--enable-gpu", "--use-angle=d3d11"])
            page, fr = renderer(browser, args.planner, args.scene, SIZE)
            fq = source.get("focalAt640") or args.stream_focal
            if not fq:
                raise ValueError("stream lens required for a nonrotating frame")
            camera = np.float64([[fq, 0, 319.5], [0, fq, 179.5], [0, 0, 1.0]])
            # Approximate matched angular resolution for the dense image matcher.
            # Undo this crop before using the actual stream intrinsics for PnP.
            zoom = fr / fq
            affine = np.float32([[zoom, 0, (1 - zoom) * 479.5], [0, zoom, (1 - zoom) * 269.5]])
            queries = [
                cv2.warpAffine(
                    cv2.cvtColor(cv2.resize(im, (960, 540)), cv2.COLOR_BGR2RGB), affine, (960, 540)
                )
                for im in images
            ]
            for g, group in enumerate(source["results"]):
                views = []
                for k in group["frames"]:
                    a = group["relativeYaw"][str(k)]
                    if all(abs(math.remainder(a - b, 2 * math.pi)) > 0.32 for _, b in views):
                        views.append((k, a))
                # Use a measured one-view hypothesis to render closer to the query and
                # challenge it from other live directions before publishing any position.
                candidates = list(group["candidates"][: args.candidates])
                initial_count = len(candidates)
                for rank, candidate in enumerate(candidates):
                    for k, delta in views[: (12 if rank >= initial_count else args.views)]:
                        eye = candidate["eye"]
                        yaw = candidate["yaw"] + delta
                        pose = [*eye, yaw, -0.015]
                        obs = source_observation(page, pose, fr)
                        if not obs:
                            continue
                        rgb, px, xyz = obs
                        key = len(evidence)
                        if not worker.submit(queries[k], [(key, rgb, px)]):
                            raise RuntimeError("GPU matcher busy")
                        reply = None
                        while worker.status == "matching":
                            reply = worker.poll()
                            if reply is None:
                                time.sleep(0.005)
                        if reply is None:
                            raise RuntimeError("GPU matcher did not return correspondences")
                        ids, xy = reply[0]
                        dst = ((xy - [479.5, 269.5]) / zoom + [479.5, 269.5] + 0.5) / 1.5 - 0.5
                        # Require distinct image patches in both images before geometric fitting.
                        selected = []
                        refs = set()
                        targets = set()
                        for n, j in enumerate(ids):
                            a = tuple((px[j] / 10).astype(int))
                            b = tuple((dst[n] / 7).astype(int))
                            if a in refs or b in targets:
                                continue
                            refs.add(a)
                            targets.add(b)
                            selected.append(n)
                        solver = Locator.__new__(Locator)
                        solver.meta = {"source": "source-map-grid", "independentScenery": True}
                        solver.origin = np.asarray(eye, dtype=np.float64)
                        src = (xyz[ids[selected]] - solver.origin).astype(np.float32)
                        measured = {}
                        fix = (
                            solver.solve_with_camera(
                                camera,
                                src,
                                dst[selected].astype(np.float32),
                                None,
                                inliers=measured if args.tracking_atlas else None,
                            )
                            if len(src) >= 24
                            else None
                        )
                        if measured:
                            anchors[len(evidence)] = measured
                        evidence.append(
                            dict(
                                group=g,
                                rank=rank,
                                site=candidate["site"],
                                sourceEye=eye,
                                frame=k,
                                delta=delta,
                                correspondences=len(src),
                                pose=fix,
                            )
                        )
                    if rank == initial_count - 1:
                        measured_rows = sorted(
                            (e for e in evidence if e["group"] == g and e["pose"]),
                            key=lambda e: -e["pose"]["supports"],
                        )
                        extra = []
                        for row in measured_rows:
                            fix = row["pose"]
                            heading = fix["heading"] - row["delta"]
                            if any(
                                math.dist(other["eye"], fix["eye"]) < 2
                                and math.cos(other["yaw"] - heading) > 0.99
                                for other in extra
                            ):
                                continue
                            extra.append(dict(eye=fix["eye"], yaw=heading, site=-1 - len(extra)))
                            if len(extra) == 3:
                                break
                        candidates.extend(extra)
                confirmed.extend(
                    consistent_views([e for e in evidence if e["group"] == g and e["pose"]])
                )
            browser.close()
    finally:
        worker.close()
    ambiguous = any(math.dist(a["eye"], b["eye"]) > 1.5 for a, b in combinations(confirmed, 2))
    result = dict(
        candidatesChecked=len(evidence),
        framesWithPose=sum(e["pose"] is not None for e in evidence),
        pose=None if not confirmed or ambiguous else max(confirmed, key=lambda p: p["supports"]),
        ambiguous=ambiguous,
        comparisons=evidence,
    )
    if args.tracking_atlas and result["pose"]:
        result["trackingAtlas"] = write_tracking_atlas(
            args.tracking_atlas, images, anchors, evidence, result["pose"], fq, source["revision"]
        )
    args.output.write_text(json.dumps(result, allow_nan=False), encoding="utf8")
    print({k: v for k, v in result.items() if k != "comparisons"}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scene", "results", "interpreter", "matcher", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--tracking-atlas", type=Path)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument("--stream-focal", type=float)
    parser.add_argument("--views", type=int, default=5)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("frames", type=Path, nargs="+")
    run(parser.parse_args())
