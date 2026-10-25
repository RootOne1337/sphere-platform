"""Offline held-out RGB -> map pose -> same-image route overlay experiment.

Only a recording is read. Media time is used as a simulated observation clock;
this never measures Android-to-model latency or grants live execution authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.policy import PolicyFrame, finite
from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import (
    RouteLocalizer,
    SparseRoute,
    map_support,
    render_guidance,
)
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def check(capture_dir, route, output, *, start=0., end=600.):
    import cv2 as cv
    import numpy as np

    if type(route) is not SparseRoute or not finite(start, 0, 600) or not finite(end, start, 600):
        raise ProtocolError("invalid_localization_probe")
    output = Path(output)
    checkpoint(output)
    output.mkdir(exist_ok=False)
    write_json(output/"intent.json", dict(scope="OFFLINE_RECORDING_ONLY", physical_actions=0,
                                         route_id=route.id, start=start, end=end))
    capture = validate_browser(capture_dir)
    capture_sha = hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
    taught_indices = set(route.source_frame_indices) if capture_sha == route.source_capture_sha256 else set()
    now = 0.
    epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
    tracker = RouteLocalizer(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal, clock=lambda: now,
                             diagnostic_partial_map=True)
    samples, elapsed, counts, excluded, proofs = [], [], Counter(), 0, 0
    index_excluded = 0
    references = set(route.reference_rgb_sha256)
    last_sample = None
    profile = route.profile
    if profile.width*capture.geometry[1] != profile.height*capture.geometry[0]:
        raise ProtocolError("localization_probe_aspect_mismatch")
    for row, decoded in decoded_browser(capture):
        seconds = row["relative_ticks_90k"]/90000
        if not start <= seconds <= end:
            continue
        if row["index"] in taught_indices:
            index_excluded += 1
            continue
        rgb = cv.resize(decoded.to_ndarray(format="rgb24"), (profile.width, profile.height), interpolation=cv.INTER_AREA)
        if hashlib.sha256(rgb.tobytes()).hexdigest() in references:
            excluded += 1
            continue
        if last_sample is not None and seconds-last_sample < .2:
            continue
        last_sample, now = seconds, seconds
        if len(samples) >= 3000:
            raise ProtocolError("localization_probe_sample_quota")
        if len(samples) % 30 == 0:
            checkpoint(output)
        frame = PolicyFrame(epoch, row["index"]+1, now, profile.width, profile.height, rgb.tobytes())
        started = time.perf_counter()
        pose = tracker.observe(frame, episode_id=episode, goal_revision=goal, scene="active")
        # 'active' is an offline experiment assumption, never a game-world check.
        elapsed.append((time.perf_counter()-started)*1000)
        sample = dict(source_index=row["index"], media_seconds=seconds, compute_ms=elapsed[-1], pose=asdict(pose))
        if pose.state == "localized" and pose.polyline_px and proofs < 4:
            name = f"overlay-{proofs+1}.png"
            drawn = np.frombuffer(render_guidance(frame, pose, clock=lambda: now), np.uint8).reshape(rgb.shape).copy()
            cv.putText(drawn, "OFFLINE / CAMERA TRACE / NO CLEARANCE", (12, 25), cv.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 0), 1)
            if not cv.imwrite(str(output/name), cv.cvtColor(drawn, cv.COLOR_RGB2BGR)):
                raise ProtocolError("localization_probe_proof_write")
            sample["proof_image"], proofs = name, proofs+1
        samples.append(sample)
        counts[pose.state] += 1
    report = dict(schema="sphere-route-localization-quality-v1", offline_media_clock=True,
        samples=samples, counts=dict(counts), reference_rgb_excluded=excluded,
        reference_indices_excluded=index_excluded, same_capture=capture_sha == route.source_capture_sha256,
        compute_ms=None if not elapsed else dict(p50=float(np.median(elapsed)),
            p95=float(np.percentile(elapsed, 95)), maximum=max(elapsed)),
        route_id=route.id, capture_manifest_sha256=capture_sha, map_support=map_support(route),
        metric_scale=None, scene_verified=False, physical_actions=0, execution_qualified=False,
        arrival_accepted=False, android_to_model_latency_known=False)
    write_json(output/"report.json", report)
    return {key: value for key, value in report.items() if key != "samples"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "route", "sha256", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--start", type=float, default=0.)
    parser.add_argument("--end", type=float, default=600.)
    args = parser.parse_args()
    print(json.dumps(check(args.capture, SparseRoute.load(args.route, sha256=args.sha256), args.output,
                           start=args.start, end=args.end), indent=2))


if __name__ == "__main__":
    main()
