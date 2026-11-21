"""Cold-start RGB check in a rectangular district using only map-rendered training views."""

import argparse
import base64
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.bake_world_course import renderer
from scripts.pilot.world_map_lab.live_destination import RoadMap
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator, features


def render(page, pose):
    image, depth = page.evaluate("p => mapReference(p)", pose)
    gray = np.frombuffer(base64.b64decode(image), np.uint8).reshape(SIZE[::-1])
    z = np.frombuffer(base64.b64decode(depth), "<u2").reshape(SIZE[::-1]).astype(float) / 128
    return gray, z


def lift(uv, depth, focal, pose):
    yaw, pitch = pose[3:]
    a, b = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    axes = np.array([[b, -a, 0], [sp * a, sp * b, -cp], [cp * a, cp * b, sp]])
    rays = np.column_stack(((uv - (np.array(SIZE) - 1) / 2) / focal, np.ones(len(uv))))
    return (pose[:3] + (rays @ axes) * depth[:, None]).astype(np.float32)


def bake(page, sites, focal, revision, output):
    detector = cv2.SIFT_create(nfeatures=600, contrastThreshold=0.018)
    offsets, views, pixels, world, desc, ids = [0], [], [], [], [], []
    for site in sites:
        for yaw in range(0, 360, 45):
            pose = [*site, math.radians(yaw), -0.045]
            gray, z = render(page, pose)
            uv, descriptors = features(gray, detector)
            if not len(uv):
                continue
            x, y = np.rint(uv).astype(int).T
            x = np.clip(x, 1, SIZE[0] - 2)
            y = np.clip(y, 1, SIZE[1] - 2)
            depth = z[y, x]
            # Avoid silhouettes where one pixel may belong to either surface.
            stable = np.maximum.reduce(
                [np.abs(z[y + dy, x + dx] - depth) for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]]
            )
            use = (depth > 1) & (depth < 180) & (stable < 0.12 + 0.02 * depth)
            if use.sum() < 36:
                continue
            pixels.append(uv[use])
            world.append(lift(uv[use], depth[use], focal, pose))
            desc.append(descriptors[use])
            ids.append(np.full(use.sum(), len(views), np.int32))
            views.append(gray)
            offsets.append(offsets[-1] + int(use.sum()))
    if not views:
        raise ValueError("no map views with stable depth")
    xyz = np.concatenate(world)
    meta = dict(
        revision=revision,
        visualTrace=sites,
        coverageRadius=4,
        source="source-map-grid",
        trainingViews=len(views),
        landmarks=len(xyz),
    )
    np.savez_compressed(
        output,
        meta=json.dumps(meta),
        intrinsics=[focal, focal, *((np.array(SIZE) - 1) / 2)],
        views=views,
        xyz=xyz,
        desc=np.concatenate(desc),
        viewIds=np.concatenate(ids),
        trackOffsets=offsets,
        trackPixels=np.concatenate(pixels),
        trackXYZ=xyz,
    )
    return meta


def check(locator, gray, focal, eye, yaw):
    locator.k[0, 0] = locator.k[1, 1] = focal
    t = time.perf_counter()
    result = locator.locate(gray)
    ms = (time.perf_counter() - t) * 1000
    if not result:
        return dict(accepted=False, ms=round(ms, 1))
    delta = result["heading"] - yaw
    return dict(
        accepted=True,
        ms=round(ms, 1),
        supports=result["supports"],
        errorM=round(math.dist(result["eye"], eye), 3),
        errorDeg=round(abs(math.degrees(math.atan2(math.sin(delta), math.cos(delta)))), 2),
    )


def main(args):
    cv2.setNumThreads(3)
    road = RoadMap(args.planner)
    rev = road.meta["placementRevision"]
    x0, y0, x1, y1 = args.atlas_bounds or args.bounds
    sites = [
        [x, y, z + 1.45]
        for x in range(x0, x1 + 1, args.step)
        for y in range(y0, y1 + 1, args.step)
        for z in road.levels(x, y)
    ]
    if not sites:
        raise ValueError("no roads in the requested district")
    args.output.mkdir(parents=True, exist_ok=True)
    print("Road samples:", len(sites), flush=True)
    bank = args.output / "district-grid.npz"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--enable-gpu", "--use-angle=d3d11"])
        page, focal = renderer(browser, args.planner, args.scene, SIZE)
        meta = bake(page, sites, focal, rev, bank)
        print("Map views:", meta["trainingViews"], flush=True)
        locator = Locator(bank, rev)
        synthetic = []
        for i, site in enumerate(sites):
            pose = [site[0] + 1.3, site[1] - 0.8, site[2] + 0.1, math.radians(i * 45 + 12), -0.055]
            gray, _ = render(page, pose)
            synthetic.append(check(locator, gray, focal, pose[:3], pose[3]))
        browser.close()
    x0, y0, x1, y1 = args.bounds
    native = []
    for sample in json.loads((args.native / "samples.json").read_bytes()).values():
        e = sample["nativeCamera"]
        # Score disjoint map regions too: any accepted pose elsewhere is a false fix.
        inside = x0 <= e[0] <= x1 and y0 <= e[1] <= y1
        rgb = cv2.imread(str(args.native / sample["file"]), cv2.IMREAD_GRAYSCALE)
        if rgb is None:
            raise ValueError("missing native frame " + sample["file"])
        hf = sample["hfov"]
        yaw = math.atan2(sample["nativeForward"][1], sample["nativeForward"][0])
        item = check(locator, rgb, SIZE[0] / (2 * math.tan(math.radians(hf) / 2)), e, yaw)
        native.append(dict(file=sample["file"], inDistrict=inside, **item))

    def stats(rows):
        accept = [r for r in rows if r["accepted"]]
        good = [r for r in accept if r["errorM"] <= 2.5 and r["errorDeg"] <= 8]
        return dict(
            total=len(rows),
            accepted=len(accept),
            correct=len(good),
            wrong=len(accept) - len(good),
            p95Ms=round(float(np.percentile([r["ms"] for r in rows], 95)), 1) if rows else None,
        )

    summary = dict(
        bounds=args.bounds,
        atlasBounds=args.atlas_bounds or args.bounds,
        step=args.step,
        gridSites=len(sites),
        landmarks=meta["landmarks"],
        trainingViews=meta["trainingViews"],
        synthetic=stats(synthetic),
        nativeDistrict=stats([r for r in native if r["inDistrict"]]),
        nativeOther=stats([r for r in native if not r["inDistrict"]]),
    )
    (args.output / "district-check.json").write_text(
        json.dumps(dict(summary=summary, synthetic=synthetic, native=native), indent=2),
        encoding="utf8",
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scene",
        type=Path,
        required=True,
        help="Map loading configuration; no itinerary poses are used",
    )
    parser.add_argument(
        "--bounds", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1")
    )
    parser.add_argument(
        "--atlas-bounds",
        type=int,
        nargs=4,
        help="Include lookalike streets around the scoring district",
    )
    parser.add_argument("--step", type=int, default=8)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument(
        "--native",
        type=Path,
        required=True,
        help="Independent game-engine stills with scoring metadata",
    )
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
