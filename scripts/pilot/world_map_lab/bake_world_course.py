"""Bake bounded-memory, route-specific landmarks from the streamed static world geometry."""

import argparse
import base64
import hashlib
import json
import math
import tempfile
import zlib
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.check_journey_rgb import H, Lane, W
from scripts.pilot.world_map_lab.native_route import native_route

SIZE = (448, 252)


def pose_for(lane, station, side=0.0, angle=0.0, pitch=-0.045):
    eye = lane.at(station).copy()
    tangent = lane.at(station + 0.8) - lane.at(station - 0.8)
    yaw = math.atan2(tangent[1], tangent[0])
    eye[:2] += side * np.array([-math.sin(yaw), math.cos(yaw)])
    eye[2] += 1.5
    return [*eye, yaw + angle, pitch]


def renderer(browser, url, route, size=SIZE):
    config = json.loads(route.read_bytes())
    with urlopen(url + "/api/world", timeout=10) as stream:
        info = json.load(stream)
    if any(config["revision"] != info[m]["placementRevision"] for m in ("walk", "drive")):
        raise ValueError("map revision differs from the selected itinerary")
    page = browser.new_page()
    page.route(
        "**/world-reference-eye",
        lambda r: r.fulfill(
            content_type="text/html",
            body='<canvas id="eye"></canvas><script type="importmap">{"imports":{"three":"/detail/js/three.module.js"}}</script>',
        ),
    )
    # Bind terrain and other route settings to the chosen itinerary rather than the current demo.
    page.route(
        "**/journey/route.json",
        lambda r: r.fulfill(content_type="application/json", body=route.read_bytes()),
    )
    page.goto(url + "/world-reference-eye")
    source = Path(__file__).with_name("observe_world_journey.mjs").read_text(encoding="utf8")
    f = page.evaluate(source, dict(width=size[0], height=size[1], model="faggio"))
    return page, f


def arrays(images):
    w, h = SIZE
    return (
        np.frombuffer(base64.b64decode(images[0]), np.uint8).reshape(h, w),
        np.frombuffer(base64.b64decode(images[1]), "<u2").reshape(h, w).astype(np.float32) / 128,
    )


def bake(route, output, url, chrome):
    paths, _, digest = native_route(route)
    config = json.loads(route.read_bytes())
    origin = np.array(paths[1][0])
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    detector = cv2.SIFT_create(nfeatures=500, contrastThreshold=0.018)
    w, h = SIZE
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp, sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, headless=True, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page, f = renderer(browser, url, route)
        target = Path(tmp) / "atlas"
        target.mkdir()
        views = []
        image_views = []
        count = 0
        with (
            (target / "xyz.f32").open("wb") as coords,
            (target / "sift.u8").open("wb") as features,
            (target / "images.z").open("wb") as images,
        ):
            for phase, leg in enumerate(config["legs"]):
                lane = Lane(leg)
                stations = np.linspace(
                    0, lane.arc[-1], math.ceil(lane.arc[-1] / (3.0 if phase == 1 else 1.5)) + 1
                )
                for i, station in enumerate(stations):
                    # Side views cover looking at the seat and turning back on foot after exiting.
                    angles = [(-3, 3)[i % 2]] if phase == 1 else [0, -40, 40, 95, -95, 180]
                    for angle in angles:
                        pose = pose_for(lane, station, 0.18 * (-1) ** i, math.radians(angle))
                        gray, z = arrays(page.evaluate("p=>mapReference(p)", pose))
                        ref = cv2.resize(gray, (W, H), interpolation=cv2.INTER_AREA)
                        depth = cv2.resize(z, (W, H), interpolation=cv2.INTER_NEAREST) * 128
                        packet = zlib.compress(ref.tobytes() + depth.astype("<u2").tobytes(), 1)
                        image_views.append(
                            dict(
                                phase=phase,
                                s=float(station),
                                pose=pose,
                                bytes=[images.tell(), len(packet)],
                            )
                        )
                        images.write(packet)
                        spread = cv2.dilate(z, None) - cv2.erode(z, None)
                        usable = (
                            np.uint8((z > 1.1) & (z < 126) & (spread < np.maximum(0.65, z * 0.055)))
                            * 255
                        )
                        usable[int(h * 0.84) :] = 0
                        key, desc = detector.detectAndCompute(gray, usable)
                        if desc is None or len(desc) < 12:
                            continue
                        uv = np.float32([k.pt for k in key])
                        x, y = np.rint(uv.T).astype(int)
                        yaw, pitch = pose[3:]
                        a, b, cp, sp = (
                            math.cos(yaw),
                            math.sin(yaw),
                            math.cos(pitch),
                            math.sin(pitch),
                        )
                        axes = np.array([[b, -a, 0], [sp * a, sp * b, -cp], [cp * a, cp * b, sp]])
                        rays = np.column_stack(
                            ((uv - [(w - 1) / 2, (h - 1) / 2]) / f, np.ones(len(uv)))
                        )
                        xyz = np.array(pose[:3]) - origin + (rays @ axes) * z[y, x, None]
                        xyz.astype("<f4").tofile(coords)
                        np.clip(desc, 0, 255).astype("u1").tofile(features)
                        views.append(
                            dict(phase=phase, s=float(station), range=[count, count + len(uv)])
                        )
                        count += len(uv)
                    if i % 400 == 0:
                        print(f"leg {phase + 1} sample {i + 1}/{len(stations)}", flush=True)
        browser.close()
        if {v["phase"] for v in views} != {0, 1, 2}:
            raise ValueError("landmarks missing in an entire leg")

        def checksum(name):
            with (target / name).open("rb") as inp:
                return hashlib.file_digest(inp, "sha256").hexdigest()

        meta = dict(
            routeSha256=digest,
            worldRevision=config["revision"],
            size=SIZE,
            focal=f,
            origin=origin.tolist(),
            count=count,
            views=views,
            imageViews=image_views,
            files={name: checksum(name) for name in ("xyz.f32", "sift.u8", "images.z")},
        )
        (target / "index.json").write_text(
            json.dumps(meta, separators=(",", ":"), allow_nan=False), encoding="utf8"
        )
        target.rename(output)
    print(f"{len(views)} views, {count} features", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("route", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8817")
    p.add_argument("--chrome")
    bake(**vars(p.parse_args()))
