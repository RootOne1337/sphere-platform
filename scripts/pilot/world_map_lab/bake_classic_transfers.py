"""Bake first-person landmarks at the two walking transfers from the native route and source mesh."""

import argparse
import json
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from scripts.pilot.world_map_lab.bake_browser_landmarks import fingerprint
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks
from scripts.pilot.world_map_lab.native_route import native_route


def bake(args):
    paths, _, route_hash = native_route(args.route)
    sys.path.insert(0, str(args.lab.resolve()))
    argv = sys.argv
    try:
        sys.argv = [argv[0], str(args.source.resolve())]
        import scooter5_visual_live_candidates_fast as scene
    finally:
        sys.argv = argv
    if not np.array_equal(np.asarray(paths[1]), scene.trace[:, :3]):
        raise ValueError("source geometry and transfer itinerary differ")
    detector = IndexedLandmarks(scene)
    xyz, descs, views = [], [], []
    count = 0
    for phase, path in zip(("approach", "depart"), (paths[0], paths[-1]), strict=True):
        coords = np.asarray(path)
        arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(coords, axis=0), axis=1))]
        for i, dist in enumerate(np.linspace(0, arc[-1], math.ceil(arc[-1] / 0.9) + 1)):
            camera = np.array([np.interp(dist, arc, column) for column in coords.T])
            camera[2] += 1.5
            station, _ = scene.locate_progress(camera - scene.origin)
            for yaw in range(0, 360, 45):
                (im, depth, _), rot, f = scene.frame(
                    scene.mesh, camera, yaw, (-1.0, 2.0)[i % 2], scene.HFOV, w=scene.W, h=scene.H
                )
                features = detector.features(im)
                if features is None:
                    continue
                uv, desc = features
                x, y = np.rint(uv).astype(int).T
                x = x.clip(0, scene.W - 1)
                y = y.clip(0, scene.H - 1)
                z = depth[y, x]
                spread = cv2.dilate(depth, None, iterations=2) - cv2.erode(
                    depth, None, iterations=2
                )
                valid = (z > 1.0) & (z < 130) & (spread[y, x] < 0.55)
                if valid.sum() < 32:
                    continue
                rays = np.column_stack(
                    ((uv[valid] + 0.5 - [scene.W / 2, scene.H / 2]) / f, np.ones(valid.sum()))
                )
                xyz.append(
                    (camera - scene.origin + (rays @ rot) * z[valid, None]).astype(np.float32)
                )
                descs.append(desc[valid])
                views.append(
                    dict(
                        s=station,
                        support=float(dist),
                        phase=phase,
                        yaw=yaw,
                        eye=camera.tolist(),
                        range=[count, count + len(xyz[-1])],
                    )
                )
                count += len(xyz[-1])
    if {v["phase"] for v in views} != {"approach", "depart"}:
        raise ValueError("both walking transfers require mapped views")
    meta = dict(
        views=views,
        route=route_hash,
        circuit=fingerprint(args.lab / "scooter5-circuit.json"),
        mesh=fingerprint(args.lab / "ariane-scooter4-mesh.npz"),
        size=[scene.W, scene.H],
        hfov=scene.HFOV,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    with TemporaryDirectory(dir=args.output.parent) as tmp:
        temp = Path(tmp) / "transfer.npz"
        np.savez_compressed(
            temp, xyz=np.concatenate(xyz), desc=np.concatenate(descs), meta=json.dumps(meta)
        )
        temp.rename(args.output)
    print(f"{len(views)} reference views, {count} mapped observations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lab", "source", "route", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    bake(parser.parse_args())
