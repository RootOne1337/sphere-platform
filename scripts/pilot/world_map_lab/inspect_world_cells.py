"""Sample the actual game's frame in every map cell with a navigable exterior surface."""

import argparse
import io
import json
import math
import re
import time
from collections import deque
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.browser_test_input import NO_POINTER_LOCK

CAMERA = re.compile(r"br_camera t=(\d+) xyz=([-\d.,]+) forward=([-\d.,]+) mode=\d+ fov=([\d.]+)")
CELL_SIDE = 512


def exterior_ocean_floor(xyz):
    """The native water query returns sea level zero outside the 12x12 half-kilometre grid."""
    xyz = np.asarray(xyz)
    return ((xyz[..., :2] < -3000) | (xyz[..., :2] >= 3000)).any(axis=-1) & (xyz[..., 2] < 0)


def sample_sites(cells, surfaces):
    """Choose the centroid of a real surface polygon, preferring roads and larger faces."""
    best = {}
    geometry = None
    for path in surfaces:
        with np.load(path, allow_pickle=False) as data:
            revision = str(data["geometry"])
            if geometry is not None and revision != geometry:
                raise ValueError("surface files refer to different geometry")
            geometry = revision
            faces = data["faces"]
        n = faces["vertices"]
        verts = faces["xyz"]
        if not np.all((n >= 3) & (n <= verts.shape[1])):
            raise ValueError("invalid navigation polygons")
        valid = np.arange(verts.shape[1])[None, :] < n[:, None]
        centers = (verts * valid[:, :, None]).sum(axis=1) / n[:, None]
        tiles = np.floor(centers[:, :2] / CELL_SIDE).astype(int)
        # Exclude slivers when a wider face is available in the same neighbourhood.
        span = ((verts[:, 1, :2] - verts[:, 0, :2]) ** 2).sum(axis=1)
        distance = np.linalg.norm(centers[:, :2] - (tiles + 0.5) * CELL_SIDE, axis=1)
        cost = distance + 20 / np.maximum(0.1, np.minimum(span, 20))
        ocean_floor = exterior_ocean_floor(centers)
        order = np.lexsort((cost, ocean_floor, tiles[:, 1], tiles[:, 0]))
        sorted_tiles = tiles[order]
        first = np.r_[True, np.any(np.diff(sorted_tiles, axis=0), axis=1)]
        for i in order[first]:
            key = tuple(map(int, tiles[i]))
            if key not in cells:
                continue
            if key in best and (not best[key]["oceanFloor"] or ocean_floor[i]):
                continue
            point = centers[i].tolist()
            vec = verts[i, 1, :2] - verts[i, 0, :2]
            yaw = math.atan2(vec[1], vec[0])
            eye = [point[0], point[1], point[2] + 1.65]
            target = [eye[0] + 12 * math.cos(yaw), eye[1] + 12 * math.sin(yaw), eye[2] - 0.65]
            best[key] = dict(
                cell=key,
                surface=path.name,
                ground=point,
                eye=eye,
                target=target,
                oceanFloor=bool(ocean_floor[i]),
            )
    return dict(
        geometry=geometry,
        sites=[best[k] for k in sorted(best, key=lambda k: (k[1], (-1) ** k[1] * k[0]))],
        cellsWithoutSample=sorted(cells - best.keys()),
    )


def mission(source, sites):
    setup, marker, _ = source.partition("camera_loop:")
    if not marker:
        raise ValueError("expected native first-person scenario")
    lines = [setup, "SET_CHAR_VISIBLE scplayer 0", "WAIT 500"]
    for index, site in enumerate(sites):
        x, y, z = site["ground"]
        eye = " ".join(f"{v:.5f}" for v in site["eye"])
        target = " ".join(f"{v:.5f}" for v in site["target"])
        lines += [
            f"REQUEST_COLLISION {x:.5f} {y:.5f}",
            f"LOAD_SCENE {x:.5f} {y:.5f} {z + 1:.5f}",
            f"SET_CHAR_COORDINATES scplayer {x:.5f} {y:.5f} {z + 0.3:.5f}",
            f"SET_FIXED_CAMERA_POSITION {eye} 0.0 0.0 0.0",
            f"POINT_CAMERA_AT_POINT {target} 2",
            "WAIT 8500" if index == 0 else "WAIT 2450",
        ]
    return "\n".join([*lines, "inspection_end:", "WAIT 0", "GOTO inspection_end", "}", ""])


def save_progress(path, payload):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(payload), encoding="utf8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.025)


def capture(url, plan, output, chrome, settle_ms=400):
    from PIL import Image
    from playwright.sync_api import sync_playwright

    sites = plan["sites"]
    targets = np.array([s["eye"] for s in sites])
    directions = np.array([s["target"] for s in sites]) - targets
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    hits = {}
    engine_error = None
    first_present = {}
    first_seen = {}
    cameras = deque(maxlen=3)
    output.mkdir(parents=True, exist_ok=False)

    def observe(msg):
        if match := CAMERA.search(msg.text):
            position, forward = (np.fromstring(match[i], sep=",") for i in (2, 3))
            cameras.append((int(match[1]), position, forward, float(match[4])))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(NO_POINTER_LOCK)
        page.on("console", observe)
        page.goto(
            url.rstrip("/")
            + "/?autostart=1&pointer=off&full=1&backend=webgpu&cache_mb=64&mods=br-game-profile&strict=1&inworld=0",
            wait_until="commit",
        )
        page.add_style_tag(content="#corner{visibility:hidden!important}")
        deadline = time.monotonic() + 240 + len(sites) * 8
        last = time.monotonic()
        while len(hits) < len(sites) and time.monotonic() < deadline:
            status = page.evaluate("()=>window.saGame?.status || {}")
            if status.get("error"):
                engine_error = str(status["error"])
                break
            if status.get("state") in (2, 4, 7):
                page.keyboard.press("Enter", delay=80)
            in_game = status.get("state") == 9 and not status.get("inMenu", True)
            if len(cameras) >= 3 and in_game and not status.get("blocked"):
                stamp, eye, forward, hfov = cameras[-1]
                delta = np.linalg.norm(targets - eye, axis=1)
                aligned = np.linalg.norm(directions - forward, axis=1) < 0.003
                i = int(np.where(aligned, delta, np.inf).argmin())
                presents = status.get("presents", 0)
                if aligned[i] and delta[i] < 0.02:
                    first_present.setdefault(i, presents)
                    first_seen.setdefault(i, stamp)
                if (
                    presents >= first_present.get(i, presents) + 3
                    and aligned[i]
                    and i not in hits
                    and delta[i] < 0.02
                    and np.linalg.norm(cameras[-3][1] - eye) < 0.01
                    and np.linalg.norm(cameras[-3][2] - forward) < 0.003
                    and stamp - first_seen.get(i, stamp) >= (max(settle_ms, 3500) if i == 0 else settle_ms)
                    and stamp - cameras[-3][0] >= 400
                ):
                    frame = page.locator("#screen").screenshot(type="jpeg", quality=92)
                    if (
                        np.linalg.norm(cameras[-1][1] - eye) < 0.01
                        and np.linalg.norm(cameras[-1][2] - forward) < 0.003
                    ):
                        im = Image.open(io.BytesIO(frame))
                        if im.size != (1920, 1080):
                            raise RuntimeError(f"unexpected frame dimensions {im.size}")
                        # Keep every real frame. Flag empty scenes for independent inspection.
                        small = np.asarray(im.resize((96, 54)).convert("L"), dtype=float)
                        file = f"cell-{sites[i]['cell'][0]}-{sites[i]['cell'][1]}.jpg"
                        if "referenceIndex" in sites[i]:
                            file = f"reference-{sites[i]['referenceIndex']}.jpg"
                        (output / file).write_bytes(frame)
                        hits[i] = dict(
                            cell=sites[i]["cell"],
                            file=file,
                            ground=sites[i]["ground"],
                            nativeCamera=eye.tolist(),
                            nativeForward=forward.tolist(),
                            hfov=hfov,
                            presents=presents,
                            **(
                                {"renderProbe": status["renderProbe"]}
                                if "renderProbe" in status
                                else {}
                            ),
                            gameTimeMs=stamp,
                            imageStd=round(float(small.std()), 2),
                            io=status.get("io"),
                            linearMemoryMiB=status.get("linearMemoryMiB"),
                        )
                        save_progress(output / "samples.json", hits)
                        last = time.monotonic()
                        if len(hits) % 20 == 0:
                            print("captured", len(hits), "of", len(sites), flush=True)
            if hits and time.monotonic() - last > 35:
                break
            page.wait_for_timeout(80)
        browser.close()
    missing = [s["cell"] for i, s in enumerate(sites) if i not in hits]
    summary = dict(
        scheduled=len(sites),
        engineError=engine_error,
        captured=len(hits),
        missing=missing,
        ioFailures=max((v["io"]["failed"] for v in hits.values()), default=0),
        flatFrames=[v["cell"] for v in hits.values() if v["imageStd"] < 5],
    )
    (output / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf8")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    build = sub.add_parser("plan")
    build.add_argument("cells", type=Path)
    build.add_argument("base_mission", type=Path)
    build.add_argument("out", type=Path)
    build.add_argument("surfaces", nargs="+", type=Path)
    run = sub.add_parser("capture")
    run.add_argument("url")
    run.add_argument("plan", type=Path)
    run.add_argument("out", type=Path)
    run.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    args = p.parse_args()
    if args.action == "plan":
        sites = sample_sites(
            {tuple(c["cell"]) for c in json.loads(args.cells.read_bytes())}, args.surfaces
        )
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out / "plan.json").write_text(json.dumps(sites, indent=2), encoding="utf8")
        (args.out / "main.sc").write_text(
            mission(args.base_mission.read_text(), sites["sites"]), encoding="ascii"
        )
        print("sites", len(sites["sites"]), "without surface", sites["cellsWithoutSample"])
    else:
        result = capture(args.url, json.loads(args.plan.read_bytes()), args.out, args.chrome)
        print(result)
        raise SystemExit(
            int(
                bool(
                    result["missing"]
                    or result["flatFrames"]
                    or result["ioFailures"]
                    or result.get("engineError")
                )
            )
        )
