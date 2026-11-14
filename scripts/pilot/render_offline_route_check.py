"""Render precomputed held-out route observations over their exact source frames.

This is a replay of an existing offline test, not live localization or an input
controller. Never interpolate a pose or carry an old overlay to another frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.route_localization import SIZE, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_workspace import resource_checkpoint


def validated_samples(report, route, capture_sha):
    if (
        report.get("schema") != "sphere-route-localization-quality-v1"
        or report.get("route_id") != route.id
        or report.get("capture_manifest_sha256") != capture_sha
        or report.get("offline_media_clock") is not True
        or report.get("physical_actions") != 0
        or report.get("execution_qualified") is not False
    ):
        raise ValueError("offline_report_binding_invalid")
    samples = report.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 3000:
        raise ValueError("offline_samples_invalid")
    result, previous = {}, -1
    for sample in samples:
        index, pose = sample.get("source_index"), sample.get("pose")
        seconds = sample.get("media_seconds")
        if (
            type(index) is not int
            or index <= previous
            or type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or seconds < 0
            or not isinstance(pose, dict)
            or pose.get("route_id") != route.id
            or pose.get("receiver_sequence") != index + 1
            or pose.get("state") not in {"unknown", "confirming", "localized"}
            or not isinstance(pose.get("source_rgb_sha256"), str)
            or len(pose["source_rgb_sha256"]) != 64
            or not isinstance(pose.get("polyline_px"), list)
        ):
            raise ValueError("offline_sample_binding_invalid")
        if capture_sha == route.source_capture_sha256 and index in route.source_frame_indices:
            raise ValueError("offline_sample_is_reference")
        points = pose["polyline_px"]
        if (
            len(points) > 16
            or pose["state"] != "localized"
            and points
            or any(
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    type(v) not in (int, float) or not 0 <= v < SIZE[i] for i, v in enumerate(point)
                )
                for point in points
            )
        ):
            raise ValueError("offline_sample_polyline_invalid")
        result[index] = sample
        previous = index
    return result


def render(capture_dir, route_path, route_sha, report_path, output):
    import av
    import cv2 as cv
    import numpy as np

    capture = validate_browser(capture_dir)
    capture_sha = hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
    route = SparseRoute.load(route_path, sha256=route_sha)
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    samples = validated_samples(report, route, capture_sha)
    if route.profile.width * capture.geometry[1] != route.profile.height * capture.geometry[0]:
        raise ValueError("offline_aspect_mismatch")
    output = Path(output)
    resource_checkpoint(output)
    output.mkdir(exist_ok=False)
    write_json(
        output / "intent.json",
        dict(
            scope="OFFLINE_PRECOMPUTED_FRAME_REPLAY",
            route_id=route.id,
            capture_manifest_sha256=capture_sha,
            report_sha256=hashlib.sha256(Path(report_path).read_bytes()).hexdigest(),
            physical_actions=0,
        ),
    )
    counts = {"unknown": 0, "confirming": 0, "localized": 0}
    written, first_tick = 0, None
    with av.open(str(output / "preview.mp4"), mode="w") as container:
        stream = container.add_stream(
            "libx264", rate=5, options={"crf": "18", "preset": "veryfast", "bf": "0"}
        )
        stream.width, stream.height, stream.pix_fmt = SIZE[0], SIZE[1], "yuv420p"
        stream.time_base = Fraction(1, 90000)
        stream.codec_context.time_base = Fraction(1, 90000)
        for row, decoded in decoded_browser(capture):
            sample = samples.get(row["index"])
            if sample is None:
                continue
            if written % 20 == 0:
                resource_checkpoint(output)
            ticks, pose = row["relative_ticks_90k"], sample["pose"]
            if abs(sample["media_seconds"] - ticks / 90000) > 1 / 90000:
                raise ValueError("offline_sample_time_mismatch")
            rgb = cv.resize(
                decoded.to_ndarray(format="rgb24"),
                (route.profile.width, route.profile.height),
                interpolation=cv.INTER_AREA,
            )
            if hashlib.sha256(rgb.tobytes()).hexdigest() != pose["source_rgb_sha256"]:
                raise ValueError("offline_sample_rgb_changed")
            view = cv.resize(rgb, SIZE, interpolation=cv.INTER_AREA)
            if pose["state"] == "localized" and len(pose["polyline_px"]) >= 2:
                points = np.rint(np.asarray(pose["polyline_px"])).astype(np.int32)
                cv.polylines(view, [points], False, (0, 0, 0), 7, cv.LINE_AA)
                cv.polylines(view, [points], False, (97, 234, 216), 3, cv.LINE_AA)
            cv.rectangle(view, (0, 0), (SIZE[0], 54), (0, 0, 0), -1)
            cv.putText(
                view,
                f"OFFLINE SAME RECORDING | {ticks / 90000:.2f}s | {pose['state'].upper()}",
                (10, 23),
                cv.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
                cv.LINE_AA,
            )
            cv.putText(
                view,
                "CAMERA TRACE ONLY - NOT ROAD / NO CONTROL",
                (10, 46),
                cv.FONT_HERSHEY_SIMPLEX,
                0.47,
                (255, 215, 110),
                1,
                cv.LINE_AA,
            )
            frame = av.VideoFrame.from_ndarray(view, format="rgb24")
            first_tick = ticks if first_tick is None else first_tick
            frame.pts, frame.time_base = ticks - first_tick, Fraction(1, 90000)
            for packet in stream.encode(frame):
                container.mux(packet)
            counts[pose["state"]] += 1
            written += 1
        for packet in stream.encode():
            container.mux(packet)
    if written != len(samples):
        raise ValueError("offline_samples_not_found")
    video = output / "preview.mp4"
    with video.open("rb") as file:
        video_sha = hashlib.file_digest(file, "sha256").hexdigest()
    result = dict(
        schema="sphere-offline-route-replay-v1",
        frames=written,
        counts=counts,
        media_time_preserved=True,
        full_video=False,
        precomputed=True,
        same_capture=capture_sha == route.source_capture_sha256,
        route_id=route.id,
        video_sha256=video_sha,
        video_bytes=video.stat().st_size,
        physical_actions=0,
        execution_qualified=False,
        metric_scale=None,
        limitations="Sampled same-recording frames, precomputed pose; no independent traversal, ground truth, or Android latency.",
    )
    write_json(output / "report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "route", "route-sha", "report", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            render(args.capture, args.route, args.route_sha, args.report, args.output), indent=2
        )
    )


if __name__ == "__main__":
    main()
