"""Compare two renderers at held-out viewpoints using the existing Scooter 5 RGB observer."""

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from scripts.pilot.world_map_lab.browser_eye import open_eye


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(args):
    sys.path.insert(0, str(args.lab))
    sys.argv = [sys.argv[0], str(args.source)]
    import scooter5_visual_live_candidates_fast as observer

    verified = json.loads((args.lab / "scooter5-verified-virtual-results.json").read_bytes())[
        "artifacts_sha256"
    ]
    for name in (
        "scooter5_visual_live_candidates_fast.py",
        "scooter5-circuit.json",
        "scooter5-visual-atlas-all-curves.npz",
    ):
        if digest(args.lab / name) != verified[name]:
            raise ValueError("different fixture: " + name)

    from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks

    indexed = IndexedLandmarks(observer)
    args.out.mkdir(parents=True, exist_ok=True)
    trace = observer.trace
    center = (trace[:, :3].min(axis=0) + trace[:, :3].max(axis=0)) * 0.5
    rows = []
    with open_eye(
        args.port,
        center,
        width=observer.W,
        height=observer.H,
        hfov=observer.HFOV,
        browser=args.browser,
    ) as eye:
        for i, s in enumerate(np.linspace(0.7, observer.dist[-1] - 1.3, 18)):
            xyz, yaw = observer.p_and_yaw(s, 0.27 if i % 2 else -0.22, 3.8 if i % 2 else -2.1)
            angle = math.degrees(yaw)
            pitch = 1.65 + 0.55 * math.sin(i)
            (native, _, _), basis, _ = observer.frame(
                observer.mesh, xyz, angle, pitch, observer.HFOV, w=observer.W, h=observer.H
            )
            browser = eye(xyz, angle, pitch)
            for kind, rgb in (("native", native), ("browser", browser)):
                cv2.setRNGSeed(137)
                start = time.perf_counter()
                fit, status, views = observer.localize(
                    rgb, max(0, s - 4), min(observer.dist[-1], s + 4)
                )
                elapsed = 1000 * (time.perf_counter() - start)
                error = heading = None
                if status == "candidate":
                    error = float(np.linalg.norm(fit[1] + observer.origin - xyz))
                    heading = math.degrees(math.acos(np.clip(fit[2] @ basis[2], -1, 1)))
                    status = "correct" if error <= 1 and heading <= 3 else "incorrect"
                rows.append(
                    dict(
                        case=i,
                        station=float(s),
                        renderer=kind,
                        status=status,
                        views=views,
                        error=error,
                        heading=heading,
                        ms=elapsed,
                    )
                )
                if i in (0, 3, 7, 11, 16):
                    cv2.imwrite(
                        str(args.out / f"{kind}-{i:02d}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                    )
            for label, offset in (
                ("browser_index", 0),
                ("wrong_district", observer.dist[-1] * 0.49),
            ):
                prior = s if not offset else (s + offset) % observer.dist[-1]
                begin = time.perf_counter()
                fit = indexed(browser, max(0, prior - 4), min(observer.dist[-1], prior + 4))
                elapsed = 1000 * (time.perf_counter() - begin)
                error = heading = None
                status = indexed.last_reason
                if fit is not None:
                    error = float(np.linalg.norm(fit[0] - xyz))
                    heading = math.degrees(math.acos(np.clip(fit[1][2] @ basis[2], -1, 1)))
                    status = "correct" if error <= 1 and heading <= 3 else "incorrect"
                rows.append(
                    dict(
                        case=i,
                        station=float(s),
                        renderer=label,
                        status=status,
                        error=error,
                        heading=heading,
                        ms=elapsed,
                    )
                )
            print(i, [x["status"] for x in rows[-4:]], flush=True)
    report = {
        "source": "independent viewpoints; known local search window plus or minus four route units",
        "hfov": observer.HFOV,
        "checks": rows,
        "results": {},
    }
    for kind in ("native", "browser", "browser_index", "wrong_district"):
        subset = [r for r in rows if r["renderer"] == kind]
        report["results"][kind] = {
            "status": dict(Counter(r["status"] for r in subset)),
            "visionP95ms": float(np.percentile([r["ms"] for r in subset], 95)),
        }
    (args.out / "cross-render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report["results"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("lab", "out", "source"):
        p.add_argument("--" + field, type=Path, required=True)
    p.add_argument("--port", type=int, default=8817)
    p.add_argument("--browser")
    run(p.parse_args())
