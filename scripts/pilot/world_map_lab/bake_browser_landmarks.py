"""Bake a route-local RGB landmark index from the textured browser view and aligned source depth."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from scripts.pilot.world_map_lab.browser_eye import open_eye
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bake(args):
    sys.path.insert(0, str(args.lab))
    sys.argv = [sys.argv[0], str(args.source)]
    import scooter5_visual_live_candidates_fast as scene

    extractor = IndexedLandmarks(scene)
    views, xyz, descriptors = [], [], []
    grays, corners, surface_points, spans = [], [], [], []
    corner_count = 0
    count = 0
    center = (scene.trace[:, :3].min(axis=0) + scene.trace[:, :3].max(axis=0)) * 0.5
    with open_eye(
        args.port, center, width=scene.W, height=scene.H, hfov=scene.HFOV, browser=args.browser
    ) as eye:
        stations = np.linspace(0, scene.dist[-1], math.ceil(scene.dist[-1] / 1.4) + 1)
        offsets = ((0.18, 3.25), (-0.18, -3.25), (0, 0))
        viewpoints = [(s, *offsets[i % 3]) for i, s in enumerate(stations)]
        if args.wide:
            # Sample the whole circuit with alternative headings and lateral camera locations.
            for direction in (-1, 1):
                viewpoints.extend((s, direction * 0.8, direction * 25.0) for s in stations[::2])
        for i, (station, side, turn) in enumerate(viewpoints):
            camera, yaw = scene.p_and_yaw(station, side, turn)
            pitch = 1.4 if i % 2 else 2.6
            rgb = eye(camera, math.degrees(yaw), pitch)
            features = extractor.features(rgb)
            if features is None:
                continue
            pixels, desc = features
            (_, depth, _), rotation, focal = scene.frame(
                scene.mesh, camera, math.degrees(yaw), pitch, scene.HFOV, w=scene.W, h=scene.H
            )
            # Subpixel features next to silhouettes cannot inherit depth across the edge.
            x, y = np.rint(pixels.T).astype(int)
            x = x.clip(0, scene.W - 1)
            y = y.clip(0, scene.H - 1)
            spread = cv2.dilate(depth, None, iterations=2) - cv2.erode(depth, None, iterations=2)
            z = depth[y, x]
            valid = (z > 1.0) & (z < 130) & (spread[y, x] < 0.55)
            if valid.sum() < 32:
                continue
            rays = np.column_stack(
                ((pixels[valid] + 0.5 - [scene.W / 2, scene.H / 2]) / focal, np.ones(valid.sum()))
            )
            points = camera - scene.origin + (rays @ rotation) * z[valid, None]
            xyz.append(points.astype(np.float32))
            descriptors.append(desc[valid])
            views.append(dict(s=float(station), **{"range": [count, count + len(points)]}))
            gray = cv2.resize(
                cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY),
                (scene.W // 2, scene.H // 2),
                interpolation=cv2.INTER_AREA,
            )
            usable = ((depth > 1.1) & (depth < 128) & (spread < 0.55)).astype(np.uint8)
            mask = cv2.resize(
                usable, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST
            )
            keys = cv2.goodFeaturesToTrack(gray, 850, 0.006, 4, mask=mask, blockSize=5)
            uv = keys[:, 0] if keys is not None else np.empty((0, 2), np.float32)
            xx, yy = np.rint(uv.T * 2).astype(int)
            rays = np.column_stack(
                ((uv * 2 + 1 - [scene.W / 2, scene.H / 2]) / focal, np.ones(len(uv)))
            )
            world = camera - scene.origin + (rays @ rotation) * depth[yy, xx, None]
            grays.append(gray)
            corners.append(uv)
            surface_points.append(world.astype(np.float32))
            spans.append([corner_count, corner_count + len(uv)])
            corner_count += len(uv)
            count += len(points)
            if i % 40 == 0:
                print(i, count, flush=True)
    if len(views) < 2:
        raise ValueError("insufficient mapped views")
    meta = dict(
        views=views,
        revision=eye.revision,
        circuit=fingerprint(args.lab / "scooter5-circuit.json"),
        size=[scene.W, scene.H],
        hfov=scene.HFOV,
    )
    tmp = args.out.with_suffix(".partial.npz")
    np.savez_compressed(
        tmp,
        xyz=np.concatenate(xyz),
        desc=np.concatenate(descriptors),
        gray=np.stack(grays),
        uv=np.concatenate(corners),
        surface=np.concatenate(surface_points),
        spans=np.array(spans),
        meta=np.array(json.dumps(meta)),
    )
    tmp.replace(args.out)
    print(len(views), count, flush=True)


def load_bank(file, lab, scene, *, revision=None):
    with np.load(file, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        if (
            meta["circuit"] != fingerprint(lab / "scooter5-circuit.json")
            or (revision is not None and meta.get("revision", revision) != revision)
            or meta["size"] != [scene.W, scene.H]
            or meta["hfov"] != scene.HFOV
        ):
            raise ValueError("browser landmark index differs from the route or camera")
        local = SimpleNamespace(
            xyz=data["xyz"],
            desc=data["desc"],
            views=meta["views"],
            origin=scene.origin,
            K=scene.K,
            W=scene.W,
            H=scene.H,
            locate_progress=scene.locate_progress,
        )
    return IndexedLandmarks(local)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("out", "lab", "source"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--wide", action="store_true")
    parser.add_argument("--browser")
    parser.add_argument("--port", default=8817, type=int)
    bake(parser.parse_args())
