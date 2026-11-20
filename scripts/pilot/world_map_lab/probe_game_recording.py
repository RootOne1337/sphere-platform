"""Evaluate the map observer on saved RGB with no route seed; never issues input."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import av
import cv2
import numpy as np

from scripts.pilot.world_map_lab.bake_browser_landmarks import load_bank
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks


def probe(args):
    sys.path.insert(0, str(args.lab))
    sys.argv = [sys.argv[0], str(args.source)]
    import scooter5_visual_live_candidates_fast as observer

    manifest = json.loads((args.input / "manifest.json").read_bytes())
    previous = json.loads(
        (args.lab / "scooter5-existing-game-footage-spot-check.json").read_bytes()
    )
    if manifest["id"] != "a98caca194924e028a241aaa2b004e2f" or not manifest["complete"]:
        raise ValueError("expected completed HUD-free Scooter 4 recording")
    samples = {c["frame"]: {"previous": c["status"], "candidates": []} for c in previous["checks"]}
    args.out.mkdir(parents=True, exist_ok=True)
    net = load_bank(args.bank, args.lab, observer) if args.bank else IndexedLandmarks(observer)
    video = args.input / "video.h264"
    if video.stat().st_size != manifest["files"][video.name]["bytes"]:
        raise ValueError("incomplete video")
    with video.open("rb") as f:
        key = hashlib.file_digest(f, "sha256").hexdigest()
    if key != "432eee6149a596316340e928245c4b2a8609fbf6c8e9ba0e2463a65e15e4f8d7":
        raise ValueError("source video digest mismatch")
    features = {}
    with av.open(str(video), format="h264") as clip:
        for i, frame in enumerate(clip.decode(video=0)):
            if i not in samples:
                continue
            image = cv2.resize(
                frame.to_ndarray(format="rgb24"),
                (observer.W, observer.H),
                interpolation=cv2.INTER_AREA,
            )
            features[i] = net.features(image)
            if i in (0, 445, 625):
                cv2.imwrite(
                    str(args.out / f"game-{i:03}.jpg"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                )
            if len(features) == len(samples):
                break
    if features.keys() != samples.keys():
        raise ValueError("missing source frames")
    begin = time.perf_counter()
    for lo in np.arange(0, observer.dist[-1], 12.0):
        hi = min(observer.dist[-1], lo + 12)
        for i, f in features.items():
            fit = net.match(f, lo, hi, require_corridor=args.require_corridor)
            strength = (net.evidence["inliers"], net.evidence["distinct"])
            old = samples[i].get("strongestRejected", {})
            if fit is None and strength > (old.get("inliers", 0), old.get("distinct", 0)):
                samples[i]["strongestRejected"] = dict(
                    **net.evidence, reason=net.last_reason, window=[float(lo), float(hi)]
                )
            if fit is not None:
                p, rot, s, n, err = fit
                samples[i]["candidates"].append(
                    dict(
                        station=s,
                        lateral=float(observer.locate_progress(p - observer.origin)[1]),
                        rotation=rot.tolist(),
                        xyz=p.tolist(),
                        heading=float(np.degrees(np.arctan2(rot[2, 1], rot[2, 0]))),
                        inliers=n,
                        reprojection=err,
                    )
                )
    for case in samples.values():
        vals = case["candidates"]
        case["status"] = (
            "missing"
            if not vals
            else (
                "ambiguous"
                if any(
                    np.linalg.norm(np.subtract(a["xyz"], b["xyz"])) > 0.6
                    for a in vals
                    for b in vals
                )
                else "candidate_unverified"
            )
        )
    data = {
        "recording": manifest["id"],
        "videoSha256": key,
        "checks": samples,
        "elapsed": time.perf_counter() - begin,
        "scope": "global search over route, independent RGB, no known true pose, no vehicle commands",
    }
    name = "game-observer" if args.require_corridor else "game-map-recognition"
    if args.bank:
        name += "-browser-bank"
    if args.result:
        name = args.result
    (args.out / (name + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print([(i, c["status"]) for i, c in samples.items()])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "lab", "source", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--result")
    p.add_argument("--require-corridor", action="store_true")
    p.add_argument("--bank", type=Path)
    probe(p.parse_args())
