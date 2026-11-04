"""Replay saved video through the scooter pose, HUD and start gates without input."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from collections import Counter
from contextlib import closing
from pathlib import Path

from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
from scripts.pilot.route_preparation_source import attempt_source


def checked_frame(root, row):
    path = (root / row["filename"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("query outside manifest directory")
    with path.open("rb") as source:
        data = source.read(384 * 1024 + 1)
    if not 100 <= len(data) <= 384 * 1024 or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("invalid replay JPEG")
    return data


def run_window(route, views, speed_reference, sidecar, rows):
    import cv2 as cv
    import numpy as np

    from motor_worker.policy import PolicyFrame
    from motor_worker.route_confirmation import ReferenceLKConfirmationLocalizer
    from motor_worker.route_descriptor_recovery import ReferenceLKRecoveryLocalizer
    from motor_worker.vehicle_route import VehicleRouteFollower
    from scripts.pilot.route_hud_profile import read_live_speed

    epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
    clock = time.perf_counter
    options = dict(capture_epoch=epoch, episode_id=episode, goal_revision=goal, clock=clock)
    tracker = (
        ReferenceLKConfirmationLocalizer(route, **options)
        if sidecar is None
        else ReferenceLKRecoveryLocalizer(route, sidecar=sidecar, **options)
    )
    plans, skipped = [], 0
    with closing(tracker):
        follower = VehicleRouteFollower(
            route, speed_reference, clock=clock, reference_rotations=views, start_mode="beginning"
        )
        first_ticks = rows[0][0]["relative_ticks_90k"]
        start = clock() + 0.02
        for sequence, (sample, jpeg) in enumerate(rows, 1):
            due = start + (sample["relative_ticks_90k"] - first_ticks) / 90000
            delay = due - clock()
            if delay < -0.1:
                skipped += 1
                continue
            if delay > 0:
                time.sleep(delay)
            image = cv.imdecode(np.frombuffer(jpeg, np.uint8), cv.IMREAD_COLOR)
            if image is None or image.shape != (540, 960, 3):
                raise ValueError("replay image dimensions")
            rgb = cv.cvtColor(image, cv.COLOR_BGR2RGB).tobytes()
            received = clock()
            frame = PolicyFrame(epoch, sequence, received, 960, 540, rgb)
            cv.setRNGSeed(17)
            pose = tracker.observe(frame, episode_id=episode, goal_revision=goal, scene="active")
            speed = read_live_speed(
                image,
                epoch=epoch,
                sequence=sequence,
                received_at=received,
                jpeg_sha256=sample["sha256"],
            )
            speed["source_rgb_sha256"] = pose.source_rgb_sha256
            # Open-loop source footage. No fabricated Android motion ACK.
            plan = follower.observe(pose, speed, motion_active=False)
            plans.append(
                dict(
                    frame=sample["frame_index"],
                    seconds=sample["relative_ticks_90k"] / 90000,
                    frameAgeMs=(clock() - due) * 1000,
                    pose=pose.state,
                    poseReason=pose.reason,
                    inliers=pose.inliers,
                    segment=pose.segment,
                    hud=speed["status"],
                    hudKmh=speed.get("speed_kmh"),
                    phase=plan["phase"],
                    pedal=plan["pedal"],
                    planReason=plan["reason"],
                    confirmationCount=plan["confirmationValidCount"],
                )
            )
    first_throttle = next((row for row in plans if row["pedal"] == "throttle"), None)
    first_fresh = next(
        (row for row in plans if row["pedal"] == "throttle" and row["frameAgeMs"] <= 250), None
    )
    return dict(
        scheduled=len(rows),
        skipped=skipped,
        poseCounts=dict(Counter(row["pose"] for row in plans)),
        hudCounts=dict(Counter(row["hud"] for row in plans)),
        planReasons=dict(Counter(row["planReason"] for row in plans)),
        firstThrottle=first_throttle,
        firstFreshThrottle=first_fresh,
        rows=plans,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--window",
        action="append",
        nargs=5,
        required=True,
        metavar=("NAME", "MANIFEST", "CAPTURE", "FROM", "TO"),
    )
    parser.add_argument("--compare-descriptor-recovery", action="store_true")
    args = parser.parse_args()
    if len(args.window) > 8:
        parser.error("at most eight bounded replay windows")
    root = Path.cwd().resolve()
    job, output = args.job.resolve(), args.output.resolve()
    if (
        not job.is_relative_to(root / ".local-pilot/reconstruction-jobs")
        or not output.is_relative_to(root / ".local-pilot")
        or output.is_relative_to(job)
        or output.exists()
    ):
        parser.error("use an existing route job and a new separate local output")

    def check_resources():
        findings = evaluate(collect(root), min_ram_gib=4.75)
        if findings:
            raise RuntimeError(f"replay resource guard: {findings}")

    check_resources()
    initialize_route_cpu_runtime()
    import cv2 as cv

    from motor_worker.route_reference_lk import ReferenceLKRoute
    from motor_worker.route_reference_view import reference_rotations
    from scripts.pilot.route_descriptor_attachment import load_descriptor_recovery
    from scripts.pilot.route_hud_profile import load_speed_reference
    from scripts.pilot.route_workspace import RouteWorkspaces

    cv.setNumThreads(2)
    active = job / "navigation/active.json"
    active_bytes = active.read_bytes()
    nav = active.parent / uuid.UUID(hex=json.loads(active_bytes)["id"]).hex
    receipt = json.loads((nav / "receipt.json").read_bytes())
    selected = attempt_source(job, nav)
    speed = load_speed_reference(job)
    methods = {"vehicle_runtime_lk": None}
    if args.compare_descriptor_recovery:
        recovery, _, _ = load_descriptor_recovery(
            nav, receipt, stamp=RouteWorkspaces._runtime_source_stamp
        )
        if recovery is None:
            raise ValueError("verified descriptor sidecar unavailable")
        methods["diagnostic_descriptor_recovery"] = recovery
    output.mkdir()
    report = dict(
        schema="sphere-vehicle-start-replay-v1",
        route=nav.name,
        geometrySha256=receipt["geometry_sha256"],
        sourceManifestSha256=receipt["source_capture_sha256"],
        physicalActions=0,
        androidFeedback=False,
        closedLoop=False,
        startMode="beginning",
        windows=[],
    )
    with closing(ReferenceLKRoute.load(nav / "route.json", sha256=receipt["sha256"])) as route:
        views = reference_rotations(selected["geometry_path"], route, receipt["geometry_sha256"])
        for label, path, capture_label, lower, upper in args.window:
            manifest_path = Path(path).resolve(strict=True)
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            start, end = float(lower), float(upper)
            if not 0 <= start < end <= 180 or end - start > 15:
                raise ValueError("replay window outside bounds")
            if manifest["schema"] != "sphere-learned-replay-queries-v1":
                raise ValueError("unknown query manifest")
            capture = next(c for c in manifest["captures"] if c["label"] == capture_label)
            frames = [
                row
                for row in capture["frames"]
                if start <= row["relative_ticks_90k"] / 90000 <= end
            ]
            ticks = [row["relative_ticks_90k"] for row in frames]
            if not 3 <= len(frames) <= 151 or any(a >= b for a, b in zip(ticks, ticks[1:])):
                raise ValueError("replay frame quota or order")
            rows = [(row, checked_frame(manifest_path.parent, row)) for row in frames]
            window = dict(
                name=label,
                sourceCapture=capture["capture_id"],
                queryManifestSha256=hashlib.sha256(manifest_bytes).hexdigest(),
                sameRecording=capture["manifest_sha256"] == route.source_capture_sha256,
                interval=[start, end],
                methods={},
            )
            report["windows"].append(window)
            for method, sidecar in methods.items():
                check_resources()
                window["methods"][method] = result = run_window(route, views, speed, sidecar, rows)
                print(label, method, {k: v for k, v in result.items() if k != "rows"}, flush=True)
                (output / "report.json").write_text(
                    json.dumps(report, indent=2, allow_nan=False), encoding="utf8"
                )
    if active.read_bytes() != active_bytes:
        raise ValueError("active map changed during replay")
    (output / "COMPLETE").touch(exist_ok=False)


if __name__ == "__main__":
    main()
