"""Map every original media timestamp to saved camera observations, read-only.

Temporal proximity is not a recovered pose. No interpolation or 3D estimation
is performed; all frame flags remain diagnostic rather than navigation permits.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path


def audit(capture, geometry_path, out):
    if out.exists():
        raise FileExistsError("output_exists")
    manifest_bytes = (capture / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    index = (capture / "frames.jsonl").read_bytes()
    geometry_bytes = geometry_path.read_bytes()
    geometry = json.loads(geometry_bytes)
    if (
        geometry.get("source_manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()
        or manifest.get("files", {}).get("frames.jsonl", {}).get("sha256")
        != hashlib.sha256(index).hexdigest()
    ):
        raise ValueError("capture_provenance_mismatch")
    frames = [json.loads(line) for line in index.decode("utf-8").splitlines()]
    cameras = geometry["cameras"]
    if (
        len(frames) != manifest["frames"]
        or len(cameras) < 2
        or any(
            cameras[i]["ticks_90k"] >= cameras[i + 1]["ticks_90k"] for i in range(len(cameras) - 1)
        )
    ):
        raise ValueError("invalid_capture_or_camera_order")
    times = [c["ticks_90k"] for c in cameras]
    selected = {c["image"] for c in cameras}
    rows = []
    for frame in frames:
        tick = frame["relative_ticks_90k"]
        pos = bisect.bisect_left(times, tick)
        neighbors = [i for i in (pos - 1, pos) if 0 <= i < len(times)]
        nearest = min(neighbors, key=lambda i: abs(times[i] - tick))
        exact = f"{frame['index']:08d}.png" in selected
        if exact and times[nearest] != tick:
            raise ValueError("source_frame_camera_time_mismatch")
        bracketed = 0 < pos < len(times) or pos < len(times) and times[pos] == tick
        gap = times[pos] - times[pos - 1] if 0 < pos < len(times) and times[pos] != tick else None
        rows.append(
            {
                "frame": frame["index"],
                "seconds": tick / 90000,
                "registered_exact": exact,
                "nearest_camera_seconds": times[nearest] / 90000,
                "nearest_camera_delta_ms": abs(times[nearest] - tick) / 90,
                "bracketed": bracketed,
                "camera_gap_ms": None if gap is None else gap / 90,
                "temporal_gap_over_1s": gap is not None and gap > 90000,
            }
        )
    deltas = sorted(r["nearest_camera_delta_ms"] for r in rows)
    p95 = deltas[max(0, (95 * len(deltas) + 99) // 100 - 1)]
    report = {
        "schema": "source-frame-vs-sfm-camera-timestamps-v1",
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "geometry_sha256": hashlib.sha256(geometry_bytes).hexdigest(),
        "source_frames": len(frames),
        "registered_exact_source_frames": sum(r["registered_exact"] for r in rows),
        "not_individually_registered": sum(not r["registered_exact"] for r in rows),
        "unbracketed_frames": sum(not r["bracketed"] for r in rows),
        "inside_temporal_gap_over_1s": sum(r["temporal_gap_over_1s"] for r in rows),
        "within_250ms_of_a_camera": sum(r["nearest_camera_delta_ms"] <= 250 for r in rows),
        "nearest_camera_p95_ms": p95,
        "source_video_not_decoded_or_modified": True,
        "temporal_nearness_does_not_prove_pose": True,
        "physical_actions": 0,
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("capture", type=Path)
    p.add_argument("geometry", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    audit(a.capture, a.geometry, a.output)
