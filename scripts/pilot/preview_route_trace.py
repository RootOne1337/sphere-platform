"""Read-only recorded-video camera-trace preview. No live localization or input.

Camera poses are interpolated from the SAME recording's SfM reference poses.
This deliberately does not pretend to estimate a pose from a new game frame.
No camera/body offset, ground plane, occlusion or collision map is fabricated.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from scripts.pilot.resource_guard import collect, evaluate


def pose_at(cameras: list[dict], ticks: int):
    import cv2
    import numpy as np

    times = [c["ticks_90k"] for c in cameras]
    if ticks < times[0] or ticks > times[-1]:
        return None
    at = max(0, bisect.bisect_right(times, ticks) - 1)
    first = cameras[at]
    A = np.asarray(first["camera_to_world"], np.float64)
    if ticks == times[at]:
        return A[:, :3], A[:, 3], "reconstruction_reference_pose"
    if at + 1 == len(cameras) or times[at + 1] - times[at] > 135000:
        return None
    B = np.asarray(cameras[at + 1]["camera_to_world"], np.float64)
    alpha = (ticks - times[at]) / (times[at + 1] - times[at])
    relative = cv2.Rodrigues(A[:, :3].T @ B[:, :3])[0]
    rotation = A[:, :3] @ cv2.Rodrigues(relative * alpha)[0]
    center = A[:, 3] * (1 - alpha) + B[:, 3] * alpha
    return rotation, center, "same_recording_interpolated_pose"


def project_ahead(cameras: list[dict], ticks: int, ahead_ms: int = 1200) -> dict:

    if type(ahead_ms) is not int or not 100 <= ahead_ms <= 2000:
        raise ValueError("invalid_trace_lookahead")
    pose = pose_at(cameras, ticks)
    if pose is None:
        return dict(points=[], poseSource="unavailable", center=None)
    rotation, center, kind = pose
    end = min(ticks + ahead_ms * 90, cameras[-1]["ticks_90k"])
    future = [c["ticks_90k"] for c in cameras if ticks < c["ticks_90k"] < end]
    future.append(end)
    k = cameras[0]["intrinsics"]
    points = []
    for when in future:
        other = pose_at(cameras, when)
        if other is None:
            break  # Never bridge an unobserved time interval.
        local = rotation.T @ (other[1] - center)
        if local[2] <= 1e-5:
            if points:
                break
            continue
        x = (k["fx"] * local[0] / local[2] + k["cx"]) / k["width"]
        y = (k["fy"] * local[1] / local[2] + k["cy"]) / k["height"]
        if not (0 <= x < 1 and 0 <= y < 1):
            if points:
                break
            continue
        points.append([float(x), float(y)])
    return dict(points=points, poseSource=kind, center=center.tolist())


def validate_geometry(geometry: dict, capture):
    import numpy as np

    cameras = geometry.get("cameras", [])
    if (
        geometry.get("schema") != "sphere-recovered-scene-v1"
        or not 2 <= len(cameras) <= 256
        or geometry.get("source_manifest_sha256")
        != hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
    ):
        raise ValueError("trace_preview_source_binding")
    previous = -1
    intrinsics = cameras[0]["intrinsics"]
    for camera in cameras:
        ticks = camera["ticks_90k"]
        matrix = np.asarray(camera["camera_to_world"], np.float64)
        if (
            type(ticks) is not int
            or not previous < ticks <= 600 * 90000
            or matrix.shape != (3, 4)
            or not np.isfinite(matrix).all()
            or not np.allclose(matrix[:, :3].T @ matrix[:, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(matrix[:, :3]), 1, atol=1e-5)
            or camera["intrinsics"] != intrinsics
            or not np.allclose(matrix[:, 3], camera["center"])
        ):
            raise ValueError("trace_preview_invalid_camera")
        previous = ticks
    if (intrinsics["width"], intrinsics["height"]) != capture.geometry or any(
        not np.isfinite(intrinsics[key]) or intrinsics[key] <= 0 for key in ("fx", "fy")
    ):
        raise ValueError("trace_preview_intrinsics")
    return cameras


def project_surface_candidates(cameras, candidates, ticks, ahead_ms=5000):
    """Experimental floor display only; stop at missing/discontinuous support.

    A local fitted plane is not a calibrated body trajectory or proof of free
    space. This function never connects separated unsupported neighborhoods.
    """
    import cv2
    import numpy as np

    if type(ahead_ms) is not int or not 100 <= ahead_ms <= 5000:
        raise ValueError("invalid_surface_lookahead")
    if len(candidates) != len(cameras) or any(
        row["ticks"] != cam["ticks_90k"] for row, cam in zip(candidates, cameras)
    ):
        raise ValueError("surface_camera_binding")
    pose = pose_at(cameras, ticks)
    if pose is None:
        return dict(segments=[], reason="pose_unavailable")
    at = max(0, bisect.bisect_right([row["ticks"] for row in candidates], ticks) - 1)
    row = candidates[at]
    if not row["accepted"]:
        return dict(segments=[], reason="no_local_surface_support")
    rotation, center, _ = pose
    normal = np.asarray(row["normal"], np.float64)
    if (
        normal.shape != (3,)
        or not np.isfinite(normal).all()
        or not np.isclose(np.linalg.norm(normal), 1, atol=1e-5)
    ):
        raise ValueError("invalid_surface_normal")
    height = normal @ center + row["offset"]
    if not np.isfinite(height) or height <= 0:
        return dict(segments=[], reason="surface_not_below_camera")
    world = [center - height * normal]
    reason = "candidate_not_body_or_clearance"
    for j in range(at + 1, min(at + 11, len(cameras))):
        row = candidates[j]
        if row["ticks"] - ticks > ahead_ms * 90:
            break
        if not row["accepted"]:
            reason = "stopped_at_missing_surface_support"
            break
        point = np.asarray(row["centerOnCandidatePlane"], np.float64)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError("invalid_surface_point")
        camera_step = np.linalg.norm(
            np.asarray(cameras[j]["center"]) - np.asarray(cameras[j - 1]["center"])
        )
        if np.linalg.norm(point - world[-1]) > max(camera_step * 2, 1e-6):
            reason = "stopped_at_surface_discontinuity"
            break
        world.append(point)
    local = (np.asarray(world) - center) @ rotation
    k = cameras[0]["intrinsics"]
    width, height = k["width"], k["height"]
    points = [
        None
        if p[2] <= 1e-5
        else np.array([k["fx"] * p[0] / p[2] + k["cx"], k["fy"] * p[1] / p[2] + k["cy"]])
        for p in local
    ]
    segments = []
    for a, b in zip(points[:-1], points[1:]):
        if a is None or b is None:
            if segments:
                break
            continue
        ok, first, last = cv2.clipLine(
            (0, 0, width, height),
            tuple(np.clip(np.rint(a), -1e6, 1e6).astype(int)),
            tuple(np.clip(np.rint(b), -1e6, 1e6).astype(int)),
        )
        if ok:
            segments.append(
                [[first[0] / width, first[1] / height], [last[0] / width, last[1] / height]]
            )
        elif segments:
            break
    return dict(segments=segments, reason=reason)


def run(capture_path: Path, geometry_path: Path, output: Path, ahead_ms: int = 1200):
    import av
    import numpy as np

    if evaluate(collect(Path.cwd()), min_ram_gib=12):
        raise ValueError("trace_preview_resource_guard")
    if type(ahead_ms) is not int or not 100 <= ahead_ms <= 2000:
        raise ValueError("invalid_trace_lookahead")
    if geometry_path.stat().st_size > 32 * 1024**2:
        raise ValueError("trace_geometry_budget")
    capture = validate_browser(capture_path)
    if len(capture.frames) > 5000:
        raise ValueError("trace_preview_frame_budget")
    geometry_bytes = geometry_path.read_bytes()
    geometry = json.loads(geometry_bytes)
    cameras = validate_geometry(geometry, capture)

    def file_digest(path):
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()

    source_paths = [
        geometry_path,
        capture.root / "video.h264",
        *(capture.root / name for name in capture.originals),
    ]
    source_hashes = {path: file_digest(path) for path in source_paths}
    output.mkdir(parents=True, exist_ok=False)
    frames = []
    width, height = capture.geometry
    with av.open(str(output / "preview.mp4"), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.time_base = Fraction(1, 90000)
        stream.codec_context.time_base = Fraction(1, 90000)
        stream.codec_context.thread_count = 2
        stream.options = {"crf": "18", "preset": "fast"}
        for row, decoded in decoded_browser(capture):
            ticks = row["relative_ticks_90k"]
            pose = project_ahead(cameras, ticks, ahead_ms)
            frames.append(dict(index=row["index"], seconds=ticks / 90000, **pose))
            decoded.pts, decoded.time_base = ticks, Fraction(1, 90000)
            for packet in stream.encode(decoded):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    if any(file_digest(path) != sha for path, sha in source_hashes.items()):
        raise ValueError("trace_preview_source_changed")
    # PCA is only an overview of arbitrary-unit camera positions, not a road map.
    centers = np.asarray([c["center"] for c in cameras])
    mean = centers.mean(axis=0)
    basis = np.linalg.svd(centers - mean, full_matrices=False)[2][:2].T
    trace = (centers - mean) @ basis
    for row in frames:
        row["mapPoint"] = (
            None
            if row["center"] is None
            else ((np.asarray(row.pop("center")) - mean) @ basis).tolist()
        )
    timeline = dict(
        schemaVersion=1,
        scope="RECORDED_CAMERA_TRACE_NOT_NAVIGATION",
        width=width,
        height=height,
        frames=frames,
        trace=trace.tolist(),
        lookaheadMs=ahead_ms,
        geometrySha256=hashlib.sha256(geometry_bytes).hexdigest(),
        sourceManifestSha256=geometry["source_manifest_sha256"],
        sameRecording=True,
        liveLocalization=False,
        groundRoute=False,
        occlusionChecked=False,
        physicalActions=0,
        sourceFilesChanged=False,
        syntheticFrames=0,
    )
    (output / "timeline.json").write_text(
        json.dumps(timeline, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    assets = Path(__file__).with_name("route_trace_viewer")
    for name in ("index.html", "viewer.js"):
        (output / name).write_bytes((assets / name).read_bytes())
    report = {key: value for key, value in timeline.items() if key not in ("frames", "trace")}
    report.update(
        frameCount=len(frames),
        framesWithPolyline=sum(len(f["points"]) >= 2 for f in frames),
        videoBytes=(output / "preview.mp4").stat().st_size,
    )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ahead-ms", type=int, default=1200)
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.geometry, args.output, args.ahead_ms)))


if __name__ == "__main__":
    main()
