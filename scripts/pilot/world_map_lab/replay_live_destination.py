"""Evaluate the live JPEG locator and goal controller on a timestamped recording, without input."""

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from scripts.pilot.world_map_lab.live_destination import RoadMap, Trip
from scripts.pilot.world_map_lab.live_destination_atlas import SIZE, Locator


def replay(folder, atlas, road, goal, interval_ms):
    source = folder / "video.h264"
    manifest = json.loads((folder / "manifest.json").read_bytes())
    clock = (folder / "frames.jsonl").read_bytes()
    if hashlib.sha256(clock).hexdigest() != manifest["files"]["frames.jsonl"]["sha256"]:
        raise ValueError("recording frame clock hash mismatch")
    frames = [json.loads(line) for line in clock.splitlines()]
    trip = Trip(road, goal, atlas.covers)
    rows = []
    next_time = 0.0
    previous_tick = -1
    cap = cv2.VideoCapture(str(source))
    try:
        with source.open("rb") as stream:
            for i, frame in enumerate(frames):
                if stream.tell() != frame["offset"] or frame["index"] != i:
                    raise ValueError("access-unit index mismatch")
                if hashlib.sha256(stream.read(frame["bytes"])).hexdigest() != frame["sha256"]:
                    raise ValueError("access-unit hash mismatch")
                if not cap.grab():
                    raise ValueError("truncated video")
                ticks = frame["relative_ticks_90k"]
                if ticks < previous_tick:
                    raise ValueError("nonmonotonic frame clock")
                previous_tick = ticks
                stamp = ticks / 90000
                if stamp < next_time:
                    continue
                next_time = stamp + interval_ms / 1000
                ok, pixels = cap.retrieve()
                if not ok:
                    raise ValueError("invalid source frame")
                if abs(pixels.shape[1] / pixels.shape[0] - SIZE[0] / SIZE[1]) > 0.012:
                    raise ValueError("unsupported aspect ratio")
                started = time.perf_counter()
                pixels = cv2.resize(pixels, SIZE, interpolation=cv2.INTER_AREA)
                ok, jpeg = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 91])
                if not ok:
                    raise ValueError("invalid jpeg")
                pose = atlas.locate(cv2.imdecode(jpeg, cv2.IMREAD_GRAYSCALE))
                decision = trip.decide(pose, stamp)
                rows.append(
                    dict(
                        index=i,
                        s=stamp,
                        ms=round(1000 * (time.perf_counter() - started), 1),
                        **decision,
                    )
                )
            if stream.read(1) or cap.grab():
                raise ValueError("unindexed frames")
    finally:
        cap.release()
    return dict(
        clip=manifest["id"],
        revision=road.meta["placementRevision"],
        frames=len(rows),
        poses=sum(row["pose"] is not None for row in rows),
        computeP95Ms=float(np.percentile([row["ms"] for row in rows], 95)) if rows else None,
        states=dict(Counter(row["reason"] for row in rows)),
        pedals=dict(Counter(row["pedal"] for row in rows)),
        deviceCommands=0,
        rows=rows,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--atlas", type=Path, required=True)
    p.add_argument("--recording", type=Path, action="append", required=True)
    p.add_argument("--goal", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--planner", default="http://127.0.0.1:8817")
    p.add_argument("--interval-ms", type=int, default=200)
    args = p.parse_args()
    if not 50 <= args.interval_ms <= 1000:
        p.error("expected 50 to 1000 milliseconds")
    cv2.setNumThreads(3)
    road = RoadMap(args.planner)
    atlas = Locator(args.atlas, road.meta["placementRevision"])
    out = [replay(folder, atlas, road, args.goal, args.interval_ms) for folder in args.recording]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf8")
    for run in out:
        print(json.dumps({k: v for k, v in run.items() if k != "rows"}))


if __name__ == "__main__":
    main()
