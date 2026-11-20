"""Measure pose coverage on the complete timestamped Scooter 4 recording without issuing commands."""

import argparse
import json
import sys
import time
from pathlib import Path

import av
import cv2
import numpy as np

from scripts.pilot.world_map_lab.bake_browser_landmarks import fingerprint, load_bank
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks
from scripts.pilot.world_map_lab.neighborhood_search import NeighborhoodSearch


def select_agreement(proposals):
    if not proposals:
        return None
    best = max(proposals, key=lambda p: p[3])
    if any(
        np.linalg.norm(best[0] - p[0]) > 0.65 or best[1][2] @ p[1][2] < 0.9985 for p in proposals
    ):
        return None
    return best


def replay(args):
    sys.path.insert(0, str(args.lab))
    sys.argv = [sys.argv[0], str(args.source)]
    import scooter5_visual_live_candidates_fast as scene

    video = args.input / "video.h264"
    digest = fingerprint(video)
    if digest != "432eee6149a596316340e928245c4b2a8609fbf6c8e9ba0e2463a65e15e4f8d7":
        raise ValueError("unexpected source recording")
    timestamps = [
        r["relative_ticks_90k"] / 90000
        for r in map(json.loads, (args.input / "frames.jsonl").read_text().splitlines())
    ]
    if any(b < a for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError("nonmonotonic capture times")
    native = IndexedLandmarks(scene)
    bank = load_bank(args.bank, args.lab, scene)
    retrieval = NeighborhoodSearch([(bank, 4), (native, 8)]) if args.shortlist else None
    latest = None
    last_global = -2
    next_sample = 0
    rows = []
    count = 0
    with av.open(str(video), format="h264") as stream:
        for i, frame in enumerate(stream.decode(video=0)):
            count += 1
            t = timestamps[i]
            if t < next_sample and i < len(timestamps) - 1:
                continue
            next_sample = (int(t * 5) + 1) / 5
            begin = time.perf_counter()
            rgb = cv2.resize(
                frame.to_ndarray(format="rgb24"), (scene.W, scene.H), interpolation=cv2.INTER_AREA
            )
            features = bank.features(rgb)
            fit = None
            method = "local"
            if latest is not None and t - latest[0] <= 1.8:
                # Reachable search in either direction; position and time come from earlier decoded images.
                radius = 2.3 + (t - latest[0]) * 15
                low, high = max(0, latest[1] - radius), min(scene.dist[-1], latest[1] + radius)
                boundaries = list(np.arange(low, high, 10.0))
                fits = [
                    candidate
                    for start in boundaries
                    for index in (bank, native)
                    if (
                        candidate := index.match(
                            features, start, min(start + 10, high), require_corridor=False
                        )
                    )
                    is not None
                ]
                fit = select_agreement(fits)
            if fit is None and t - last_global >= 1.2:
                method = "global"
                last_global = t
                fits = [
                    candidate
                    for start in (
                        retrieval.suggest(features)
                        if retrieval
                        else np.arange(0, scene.dist[-1], 12)
                    )
                    for index in (bank, native)
                    if (
                        candidate := index.match(
                            features, start, min(start + 12, scene.dist[-1]), require_corridor=False
                        )
                    )
                    is not None
                ]
                fit = select_agreement(fits)
            sample = dict(frame=i, capture_s=t, search=method, station=None, lateral=None)
            if fit is not None:
                eye, rot, station, n, error = fit
                latest = (t, station)
                sample.update(
                    station=station,
                    lateral=scene.locate_progress(eye - scene.origin)[1],
                    xyz=eye.tolist(),
                    rotation=rot.tolist(),
                    supports=n,
                    error_px=error,
                )
            sample["ms"] = 1000 * (time.perf_counter() - begin)
            rows.append(sample)
            if len(rows) % 30 == 0:
                print(len(rows), i, sum(r["station"] is not None for r in rows), flush=True)
    if count != len(timestamps):
        raise ValueError("recording and access-unit table differ")
    fixed = [r for r in rows if r["station"] is not None]
    gaps = np.diff([0.0] + [r["capture_s"] for r in fixed] + [timestamps[-1]])
    report = dict(
        videoSha256=digest,
        shortlisted=bool(retrieval),
        duration=timestamps[-1],
        decoded=count,
        sampled=len(rows),
        located=len(fixed),
        within_corridor=sum(r["lateral"] <= 2.2 for r in fixed),
        longest_fix_interval_s=float(max(gaps)),
        latency_p95_ms=float(np.percentile([r["ms"] for r in rows], 95)),
        rows=rows,
    )
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({k: v for k, v in report.items() if k != "rows"}, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("input", "bank", "out", "lab", "source"):
        p.add_argument("--" + field, type=Path, required=True)
    p.add_argument("--shortlist", action="store_true")
    replay(p.parse_args())
