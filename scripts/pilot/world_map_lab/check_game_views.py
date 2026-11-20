"""Compare predicted game views with an independent render and nearby competing poses."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import av
import cv2
import numpy as np

from scripts.pilot.world_map_lab.browser_eye import open_eye


def edges(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0.85)
    lines = cv2.Canny(gray, 38, 90) > 0
    # The upper sky and the instrument area are especially sensitive to dynamic appearance.
    lines[: int(0.12 * len(lines))] = False
    lines[int(0.9 * len(lines)) :] = False
    gradx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    grady = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    angle = (np.arctan2(grady, gradx) + np.pi) % np.pi
    segments = [
        lines & (abs((angle - k * np.pi / 4 + np.pi / 2) % np.pi - np.pi / 2) < np.pi * 0.15)
        for k in range(4)
    ]
    distances = [cv2.distanceTransform((~g).astype("uint8"), cv2.DIST_L2, 3) for g in segments]
    return segments, distances


def cost(actual, rendered):
    losses = []
    for i in range(4):
        for a, b in ((actual, rendered), (rendered, actual)):
            if np.any(a[0][i]):
                losses.append(np.minimum(b[1][i][a[0][i]], 12).mean())
    return float(np.mean(losses)) if losses else 12.0


def run(args):
    candidates = json.loads((args.out / args.candidates).read_bytes())
    with (args.input / "video.h264").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != candidates["videoSha256"]:
            raise ValueError("source video digest mismatch")
    pools = [candidates]
    if args.also:
        second = json.loads((args.out / args.also).read_bytes())
        if (
            second["videoSha256"] != candidates["videoSha256"]
            or second["checks"].keys() != candidates["checks"].keys()
        ):
            raise ValueError("incompatible alternative observations")
        pools.append(second)
    checks = {}
    for key in candidates["checks"]:
        proposals = [p for pool in pools for p in pool["checks"][key]["candidates"]]
        if not proposals:
            continue
        # Nearby proposals must agree in both position and view direction.
        best = min(proposals, key=lambda p: p["reprojection"])
        if all(
            np.linalg.norm(np.subtract(best["xyz"], p["xyz"])) < 0.6
            and np.dot(best["rotation"][2], p["rotation"][2]) > math.cos(math.radians(3))
            for p in proposals
        ):
            checks[int(key)] = best
    if not checks:
        raise ValueError("no isolated map proposals")
    center = np.asarray([c["xyz"] for c in checks.values()]).mean(axis=0)
    stats = []
    with (
        open_eye(
            args.port, center, width=768, height=432, hfov=115.58, browser=args.browser
        ) as eye,
        av.open(str(args.input / "video.h264"), format="h264") as clip,
    ):
        for i, frame in enumerate(clip.decode(video=0)):
            if i not in checks:
                continue
            c = checks[i]
            p = np.array(c["xyz"])
            rot = np.array(c["rotation"])
            rgb = cv2.resize(
                frame.to_ndarray(format="rgb24"), (768, 432), interpolation=cv2.INTER_AREA
            )
            target = edges(rgb)
            yaw = math.atan2(rot[2, 1], rot[2, 0])
            pitch = math.asin(np.clip(rot[2, 2], -1, 1))
            right = np.array([math.sin(yaw), -math.cos(yaw), 0])
            ahead = np.array([math.cos(yaw), math.sin(yaw), 0])
            roll = math.atan2(rot[0] @ np.cross(rot[2], right), rot[0] @ right)
            alternatives = [
                ("candidate", 0, 0, 0),
                ("left", -2, 0, 0),
                ("right", 2, 0, 0),
                ("behind", 0, -4, 0),
                ("ahead", 0, 4, 0),
                ("turn-left", 0, 0, 8),
                ("turn-right", 0, 0, -8),
            ]
            scores = {}
            for key, side, forward, turn in alternatives:
                image = eye(
                    p + side * right + forward * ahead,
                    math.degrees(yaw) + turn,
                    math.degrees(pitch),
                    math.degrees(roll),
                )
                scores[key] = cost(target, edges(image))
                if key == "candidate":
                    cv2.imwrite(
                        str(args.out / f"game-{i:03d}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                    )
                    cv2.imwrite(
                        str(args.out / f"pose-{i:03d}.jpg"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                    )
            rivals = min(v for k, v in scores.items() if k != "candidate")
            stats.append(
                dict(
                    frame=i,
                    station=c["station"],
                    lateral=c["lateral"],
                    scores=scores,
                    rank=1 + sum(v < scores["candidate"] for v in scores.values()),
                    improvement=1 - scores["candidate"] / max(rivals, 1e-6),
                )
            )
    if {r["frame"] for r in stats} != checks.keys():
        raise ValueError("missing evaluation frames")
    (args.out / args.result).write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print([(r["frame"], r["rank"], round(r["improvement"], 2)) for r in stats])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--port", type=int, default=8817)
    p.add_argument("--browser")
    p.add_argument("--candidates", default="game-map-recognition.json")
    p.add_argument("--also")
    p.add_argument("--result", default="independent-views.json")
    run(p.parse_args())
