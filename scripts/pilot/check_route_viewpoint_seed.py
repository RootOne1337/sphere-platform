"""Compare direct and rotation-seeded LK on the same saved JPEGs and views."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from contextlib import closing
from pathlib import Path

from scripts.pilot.check_vehicle_start_replay import checked_frame
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime


def run(args, root):
    findings = evaluate(collect(root), min_ram_gib=4.75)
    if findings:
        raise RuntimeError(f"viewpoint probe resource guard: {findings}")
    initialize_route_cpu_runtime()
    import cv2 as cv
    import numpy as np

    from motor_worker.policy import PolicyFrame
    from motor_worker.route_reference_lk import (
        ReferenceLKLocalizer,
        ReferenceLKRoute,
        prepare_feature_gray,
    )
    from scripts.pilot.check_route_coarse_retrieval import evaluate_reference
    from scripts.pilot.route_viewpoint_seed import choose_rotation_seed

    cv.setNumThreads(1)
    active = args.job / "navigation/active.json"
    active_bytes = active.read_bytes()
    navigation = active.parent / uuid.UUID(hex=json.loads(active_bytes)["id"]).hex
    receipt = json.loads((navigation / "receipt.json").read_bytes())
    manifest = json.loads(args.manifest.read_bytes())
    if manifest["schema"] != "sphere-learned-replay-queries-v1":
        raise ValueError("unexpected query manifest")
    capture = next(item for item in manifest["captures"] if item["label"] == args.capture)
    epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
    rows = []
    began = time.monotonic()
    with closing(ReferenceLKRoute.load(navigation / "route.json", sha256=receipt["sha256"])) as route:
        if any(not 0 <= ref < len(route.camera_trace) for ref in args.refs):
            raise ValueError("reference index outside the active map")
        with closing(ReferenceLKLocalizer(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal)) as localizer:
            arrays = localizer._cache.arrays
            for index, sample in enumerate(capture["frames"][:args.frames], 1):
                if time.monotonic() - began >= 60:
                    raise TimeoutError("viewpoint probe time budget")
                jpeg = checked_frame(args.manifest.parent, sample)
                image = cv.imdecode(np.frombuffer(jpeg, np.uint8), cv.IMREAD_COLOR)
                if image is None or image.shape != (540, 960, 3):
                    raise ValueError("invalid probe dimensions")
                rgb = cv.cvtColor(image, cv.COLOR_BGR2RGB)
                frame = PolicyFrame(epoch, index, time.monotonic(), 960, 540, rgb.tobytes())
                gray = prepare_feature_gray(frame)
                for ref in args.refs:
                    started = time.perf_counter()
                    cv.setRNGSeed(17)
                    direct, direct_pose = evaluate_reference(localizer, gray, ref)
                    seed = choose_rotation_seed(arrays["grays"][ref], gray, localizer.mask, localizer.K)
                    comparison = dict(frame=sample["frame_index"], sha256=sample["sha256"], reference=ref,
                                      ticks=sample["relative_ticks_90k"], directRetained=direct,
                                      directPnP=0 if direct_pose is None else direct_pose[2])
                    if seed is not None:
                        transform, score, yaw, pitch = seed
                        first, last = map(int, arrays["offsets"][ref:ref + 2])
                        pixels = arrays["pixels"][first:last].reshape(1, -1, 2)
                        guess = cv.perspectiveTransform(pixels, transform).reshape(-1, 2)
                        cv.setRNGSeed(17)
                        count, pose = evaluate_reference(localizer, gray, ref, initial_pixels=guess)
                        comparison.update(score=score, yaw=yaw, pitch=pitch, seededRetained=count,
                                          seededPnP=0 if pose is None else pose[2])
                    comparison["elapsedMs"] = (time.perf_counter() - started) * 1000
                    rows.append(comparison)
    if active.read_bytes() != active_bytes:
        raise ValueError("active route changed during probe")
    return dict(schema="sphere-reference-viewpoint-probe-v1", geometrySha256=receipt["geometry_sha256"],
                capture=capture["capture_id"], sameRecording=capture["manifest_sha256"] == receipt["source_capture_sha256"],
                physicalActions=0, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--refs", required=True, type=int, nargs="+")
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    args.job, args.manifest, args.output = (path.resolve() for path in (args.job, args.manifest, args.output))
    local = root / ".local-pilot"
    if (not 1 <= args.frames <= 12 or not 1 <= len(args.refs) <= 8 or len(set(args.refs)) != len(args.refs)
            or not args.job.is_relative_to(local / "reconstruction-jobs")
            or not args.manifest.is_relative_to(local) or not args.output.is_relative_to(local)
            or args.output.is_relative_to(local / "reconstruction-jobs") or args.output.exists()):
        parser.error("use bounded frames/references, an existing job and a new local output file")
    result = run(args, root)
    with args.output.open("x", encoding="utf8") as file:
        json.dump(result, file, indent=2, allow_nan=False)
    print(len(result["rows"]), sum(row["directPnP"] > 0 for row in result["rows"]),
          sum(row.get("seededPnP", 0) > 0 for row in result["rows"]))


if __name__ == "__main__":
    main()
