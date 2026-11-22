"""Verify image-retrieved map candidates using RootSIFT and the source depth."""

import argparse
import base64
import hashlib
import json
import math
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.bake_world_course import renderer
from scripts.pilot.world_map_lab.check_destination_district import lift
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator, features
from scripts.pilot.world_map_lab.verify_world_scene_candidates import consistent_views, write_tracking_atlas


def reference(page, pose, focal, detector):
    encoded, packed = page.evaluate("p=>mapReferenceRGBD(p)", pose)
    image = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), 0)
    depth = np.frombuffer(base64.b64decode(packed), "<u2").reshape(SIZE[::-1]) / 128.0
    pixels, descriptors = features(image, detector)
    if descriptors is None:
        return None
    x, y = pixels.round().astype(int).T
    x, y = np.clip(x, 1, SIZE[0] - 2), np.clip(y, 1, SIZE[1] - 2)
    z = depth[y, x]
    variation = np.maximum.reduce(
        [np.abs(depth[y + dy, x + dx] - z) for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))]
    )
    keep = (z > 1) & (z < 140) & (variation < 0.18 + 0.03 * z)
    if np.count_nonzero(keep) < 30:
        return None
    return lift(pixels[keep], z[keep], focal, pose), descriptors[keep]


def mutual_matches(matcher, left, right):
    if len(left) < 2 or len(right) < 2:
        return []

    def distinct(a, b):
        return {
            first.queryIdx: first.trainIdx
            for first, second in matcher.knnMatch(a, b, k=2)
            if first.distance < 0.78 * second.distance
        }

    backward = distinct(right, left)
    return [(i, j) for i, j in distinct(left, right).items() if backward.get(j) == i]


def run(args):
    retrieved = json.loads(args.results.read_bytes())
    scene = json.loads(args.scene.read_bytes())
    if retrieved["revision"] != scene["revision"] or retrieved["frameDigests"] != [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in args.frames
    ]:
        raise ValueError("scene or RGB differs from the retrieval inputs")
    fq = retrieved.get("focalAt640") or args.stream_focal
    if not fq or not 80 <= fq <= 1200 or args.output.exists():
        raise ValueError("expected calibrated RGB and a fresh output")
    images = [cv2.imread(str(path)) for path in args.frames]
    if any(image is None for image in images):
        raise ValueError("missing query image")
    cv2.setNumThreads(2)
    detector = cv2.SIFT_create(nfeatures=1800, contrastThreshold=0.016)
    matcher = cv2.BFMatcher()
    query = [
        features(cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), SIZE, interpolation=cv2.INTER_AREA), detector)
        for im in images
    ]
    camera = np.float64([[fq, 0, 319.5], [0, fq, 179.5], [0, 0, 1]])
    evidence, anchors, confirmed = [], {}, []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--enable-gpu", "--use-angle=d3d11"])
        try:
            page, source_focal = renderer(browser, args.planner, args.scene, SIZE)
            for group_id, group in enumerate(retrieved["results"]):
                observations = []
                for target in group["candidates"][:6]:
                    for index in group["frames"][:6]:
                        pixels, desc = query[index]
                        if desc is None:
                            continue
                        delta = group["relativeYaw"][str(index)]
                        for perturb in (0, -0.18, 0.18):
                            eye = target["eye"]
                            ref_pose = [*eye, target["yaw"] + delta + perturb, -0.045]
                            ref = reference(page, ref_pose, source_focal, detector)
                            if ref is None:
                                continue
                            points, other = ref
                            pairs = mutual_matches(matcher, other, desc)
                            fix, inliers = None, {}
                            if len(pairs) >= 24:
                                a, b = np.array(pairs).T
                                solver = Locator.__new__(Locator)
                                solver.meta = {"source": "source-map-grid", "independentScenery": True}
                                solver.origin = np.asarray(eye, dtype=float)
                                fix = solver.solve_with_camera(
                                    camera, (points[a] - solver.origin).astype(np.float32),
                                    pixels[b].astype(np.float32), None, inliers=inliers,
                                )
                            row = dict(group=group_id, site=target["site"], sourceEye=eye,
                                       frame=index, delta=delta, pairs=len(pairs), pose=fix)
                            if fix:
                                anchors[len(evidence)] = inliers
                                observations.append(row)
                            evidence.append(row)
                            if fix:
                                break
                confirmed.extend(consistent_views(observations))
        finally:
            browser.close()
    ambiguous = any(math.dist(a["eye"], b["eye"]) > 1.5 for a, b in combinations(confirmed, 2))
    pose = None if ambiguous else max(confirmed, key=lambda item: item["supports"], default=None)
    result = dict(method="rootsift", candidatesChecked=len(evidence), pose=pose, ambiguous=ambiguous,
                  framesWithPose=len({row["frame"] for row in evidence if row["pose"]}), comparisons=evidence)
    if args.tracking_atlas and pose:
        result["trackingAtlas"] = write_tracking_atlas(
            args.tracking_atlas, images, anchors, evidence, pose, fq, retrieved["revision"]
        )
    args.output.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("scene", "results", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--tracking-atlas", type=Path)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument("--stream-focal", type=float)
    parser.add_argument("frames", type=Path, nargs="+")
    answer = run(parser.parse_args())
    print({key: value for key, value in answer.items() if key != "comparisons"}, flush=True)
