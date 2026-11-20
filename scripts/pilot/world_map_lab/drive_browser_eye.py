"""Closed-loop browser acceptance using the Scooter 5 observer, visual pace follower and vehicle fixture."""

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import replace
from hashlib import file_digest, sha256
from pathlib import Path

import av
import cv2
import numpy as np

from scripts.pilot.world_map_lab.bake_browser_landmarks import load_bank
from scripts.pilot.world_map_lab.browser_eye import open_eye
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks
from scripts.pilot.world_map_lab.patch_references import PatchReferences
from scripts.pilot.world_map_lab.track_landmarks import LandmarkTrack
from scripts.pilot.world_map_lab.verify_stationary_view import rendered_agreement


def drive(sim, visual, frame, writer, scenario, indexed, use_tracks, patches):
    from scooter5_atlas_fusion_fast import AtlasFusion
    from scooter5_surface_recovery import SurfaceRecovery, verify_surface_candidate

    mode = "scan"
    width, height = sim.proto.profile.width, sim.proto.profile.height
    if width * visual.H != height * visual.W:
        raise ValueError("controller and observer aspect ratios differ")
    focal = visual.F * width / visual.W
    proto = replace(
        sim.proto,
        intrinsics=(focal, focal, width / 2, height / 2),
    )
    pace = sim.VisualPace(proto)
    surface = SurfaceRecovery(visual)
    fusion = AtlasFusion(visual)
    all_views = visual.views
    tracks = LandmarkTrack(visual, max_travel=3.0 if patches else None) if use_tracks else None
    last_speed_at_fix = 0.0
    prior_s = 0.0
    prior_v = 0.0
    reset_count = 0
    pending_static = []
    since_abs_t = 0.0
    stable_yaw = float(sim.angles[0])
    now = 0.0
    driver = sim.VisualPaceFollower(
        proto,
        pace,
        clock=lambda: now,
        reference_rotations=tuple(map(sim.rotation, sim.angles)),
        max_seconds=120,
        pace_cap=25,
        pursuit_lookahead_seconds=0.35,
        terminal_approach=True,
    )
    angle = float(sim.angles[0])
    vehicle = sim.trace[0].copy()
    if scenario in ("shifted", "dim"):
        vehicle[:2] += 0.25 * np.array([-math.sin(angle), math.cos(angle)])
        angle += math.radians(2.5)
    velocity = wheel = progress_estimate = last_seen = 0.0
    loss_start = None
    last_moving = -100.0
    last_pan = -100.0
    pan = 0.0
    scan_attempt = 0
    scan_anchor = None
    counts = Counter()
    rows = []
    pan_sequence = (-15.0, -27.0, 14.0, 26.0, -39.0, 38.0, 0.0)
    interval = 0.20
    outcome = "time_limit"
    min_substep_clearance = float(sim.map_margin(vehicle))
    substep_count = 0
    clock = time.perf_counter()
    max_time = 105
    for seq in range(1, int(max_time / interval) + 1):
        now = seq * interval
        p = vehicle + sim.base
        pitch = 2.0 + 0.45 * math.sin(now * 1.07)
        if loss_start is not None and now - loss_start >= 1.20 and now - last_pan >= 1.1:
            pan = pan_sequence[scan_attempt % len(pan_sequence)]
            scan_attempt += 1
            last_pan = now
        elif (
            scan_anchor is not None
            and progress_estimate > scan_anchor + 8.0
            and now - last_pan > 0.2
        ):
            pan = math.copysign(max(0.0, abs(pan) - 4.0), pan)
            if abs(pan) < 1.0e-6:
                scan_anchor = None
            last_pan = now
        captured = time.perf_counter()
        capture = frame(p, math.degrees(angle) + pan, pitch)
        frame_ready = time.perf_counter()
        if scenario == "dim":
            capture = np.asarray(228 * (capture.astype(np.float32) / 255.0) ** 1.14, dtype=np.uint8)
        if capture.shape != (height, width, 3):
            raise ValueError("unexpected browser capture geometry")
        digest = sha256(capture.tobytes()).hexdigest()
        image = cv2.resize(capture, (visual.W, visual.H), interpolation=cv2.INTER_AREA)
        lower = max(0.0, progress_estimate - 2.0)
        upper = min(visual.dist[-1], progress_estimate + min(36.0, 3.5 + 10.5 * (now - last_seen)))
        if not driver.started and reset_count == 0:
            lower, upper = 0.0, 2.1
        wide_stopped_search = loss_start is not None and now - loss_start >= 2.25 and prior_v < 0.30
        if driver.started or reset_count:
            uncertainty = min(1.65, 0.67 + 0.22 * max(0.0, now - since_abs_t))
            if wide_stopped_search:
                uncertainty = min(6.5, max(uncertainty, 2.1 + 0.7 * (now - loss_start - 2.25)))
            lower = max(0.0, prior_s - uncertainty)
            upper = min(visual.dist[-1], prior_s + uncertainty)
        target_angle = stable_yaw + math.radians(pan)
        choices = [v for v in all_views if lower - 2.6 < v["s"] < upper + 2.6]

        def rank(v):
            return 0.35 * abs(v["s"] - prior_s) + 2.65 * abs(
                (v["yaw"] - target_angle + math.pi) % (2 * math.pi) - math.pi
            )

        visual.views = sorted(choices, key=rank)[:58]
        start = time.perf_counter()
        direct = False
        found = None
        if tracks and wide_stopped_search:
            coast_distance = last_speed_at_fix * 0.4 + last_speed_at_fix**2 / (2 * 3.0)
            upper = min(
                visual.dist[-1], max(upper, progress_estimate + min(24.0, 2.0 + coast_distance))
            )
            lower = max(0.0, min(lower, progress_estimate - 2.0))
            choices = [v for v in all_views if lower - 2.6 < v["s"] < upper + 2.6]
            visual.views = sorted(choices, key=rank)[:90]
        tracked = tracks.track(image, now, lower, upper) if tracks else None
        patch = None
        if tracked is None and patches is not None:
            patch = patches.observe(image, lower, upper, prior_s)
        alt = tracked if tracked is not None else patch
        if alt is None and indexed:
            alt = indexed(image, lower, upper)
        putatives = patches.putatives if patch is not None else getattr(indexed, "putatives", None)
        if alt is not None:
            found, rotation, loc_s, evidence, error_px = alt
            status = (
                "tracked_pnp"
                if tracked is not None
                else "surface_quorum"
                if patch is not None
                else "indexed_quorum"
            )
            direct = tracked is None
        else:
            fit, status, _ = visual.localize(image, lower, upper)
            if status == "candidate":
                evidence, relative, _, loc_s, _, rotation = fit
                found = relative + visual.origin
                error_px = 1.0
                direct = True
            else:
                fused, fused_status, _ = fusion.find(image, lower, upper)
                if fused_status == "candidate":
                    evidence, relative, _, loc_s, _, rotation, error_px = fused
                    found = relative + visual.origin
                    status = "fused"
                    direct = True
        if found is None and now - last_pan > 0.6:
            fixed = surface.estimate(image, now, lower, upper)
            if fixed is not None:
                found, rotation, evidence, error_px = (
                    fixed.center,
                    fixed.rotation,
                    min(fixed.inliers, 100),
                    None,
                )
                status = "surface"
                loc_s, _ = visual.locate_progress(found - visual.origin)
        still_evidence = None
        if found is not None and wide_stopped_search and abs(loc_s - prior_s) > 1.20:
            checked, reason_check = verify_surface_candidate(
                visual, image, found, rotation, lower, upper
            )
            eligible = False
            checked_pose = None
            if checked is not None:
                checked_pose = checked.center, checked.rotation
                still_evidence = "photometric_surface"
            elif patches and status in ("surface_quorum", "indexed_quorum", "fused", "candidate"):
                if rendered_agreement(visual, image, found, rotation):
                    checked_pose = found, rotation
                    still_evidence = "independent_render"
                else:
                    still_evidence = reason_check
            if checked_pose is not None:
                point_now, rotation_now = checked_pose
                # A stationary camera pan must change the view while holding the same camera center.
                a = math.radians(pan)
                c, s = math.cos(a), math.sin(a)
                body = rotation_now @ np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
                pending_static = [p for p in pending_static if now - p[0] < 6.8]
                eligible = any(
                    abs(old_pan - pan) >= 12
                    and np.linalg.norm(point - point_now) < 0.46
                    and bool(old_body[2] @ body[2] > 0.997)
                    for _, old_pan, point, old_body in pending_static
                )
                pending_static.append((now, pan, point_now, body))
                if eligible:
                    found, rotation = checked_pose
                    loc_s, _ = visual.locate_progress(found - visual.origin)
            if eligible:
                # The stopped recovery begins the driver's ordinary RGB quorum from the verified place.
                driver = sim.VisualPaceFollower(
                    proto,
                    pace,
                    clock=lambda: now,
                    reference_rotations=tuple(map(sim.rotation, sim.angles)),
                    max_seconds=120,
                    pace_cap=25,
                    pursuit_lookahead_seconds=0.35,
                    terminal_approach=True,
                    start_mode="recognized_route",
                )
                reset_count += 1
                status = "stationary_consensus"
                direct = True
            else:
                found = None
                status = "stationary_confirmation_pending"
        reason_surface = surface.reason if not direct else None
        search_ms = (time.perf_counter() - start) * 1000
        geometry = {}
        camera = None
        supports = []
        if found is not None:
            if direct and tracks and indexed is not None and tracked is None:
                tracks.seed(image, putatives, found, rotation, now)
            camera = dict(xyz=found.tolist(), rotation=rotation.tolist(), station=float(loc_s))
            if status in ("indexed_quorum", "surface_quorum") and putatives is not None:
                points, pixels = putatives
                view = (points - (found - visual.origin)) @ rotation.T
                visible = view[:, 2] > 0.5
                projected = view @ visual.K.T
                errors = np.linalg.norm(
                    projected[:, :2] / np.maximum(projected[:, 2:], 0.1) - pixels, axis=1
                )
                supports = (
                    pixels[visible & (errors < 1.8)][::3][:80] / [visual.W, visual.H]
                ).tolist()
            surface.observe(now, found, rotation, direct)
            if pan:
                a = math.radians(pan)
                c, s = math.cos(a), math.sin(a)
                rotation = rotation @ np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
                if scan_anchor is None:
                    scan_anchor = loc_s
                scan_attempt = 0
            stable_yaw = math.atan2(rotation[2, 1], rotation[2, 0])
            prior_s = loc_s
            since_abs_t = now
            condition = found - sim.base
            coeff = np.clip(
                np.sum((condition - sim.trace[:-1]) * sim.delta, axis=1) / sim.length**2, 0, 1
            )
            dist = np.linalg.norm(sim.trace[:-1] + coeff[:, None] * sim.delta - condition, axis=1)
            i = int(np.argmin(dist))
            geometry = dict(
                center=tuple(condition.tolist()),
                rotation=tuple(rotation.ravel().tolist()),
                segment=i,
                progress_units=float(sim.arc[i] + coeff[i] * sim.length[i]),
                cross_track_units=float(dist[i]),
                inliers=int(evidence),
                median_error_px=error_px * width / visual.W if error_px is not None else None,
            )
            progress_estimate = max(progress_estimate, loc_s)
            last_seen = now
            loss_start = None
        else:
            if loss_start is None:
                loss_start = now
        pose = sim.RoutePose(
            "localized" if geometry else "unknown",
            "scooter5_vision" if geometry else "route_pose_not_verified",
            proto.id,
            proto.world_revision,
            "6ee5b918-77c3-4fb0-b288-0c17e21a3493",
            seq,
            now - 0.025,
            now,
            digest,
            (width, height),
            **geometry,
        )
        obs = pace.observe(pose, now)
        if obs is not None:
            prior_v = min(10.0, max(0.0, obs / pace.scale))
            if obs > 0.4:
                last_moving = now
            if geometry:
                last_speed_at_fix = prior_v
        movement_likely = bool(last_moving > now - 1.95)
        observed = dict(
            status="accepted",
            visual_pace=obs,
            epoch=pose.capture_epoch,
            sequence=seq,
            received_at=pose.received_at,
            source_rgb_sha256=digest,
        )
        plan = driver.observe(pose, observed, motion_active=movement_likely)
        pedal = plan["pedal"]
        # The safety adapter uses the last visual pace and the time of loss, never simulation velocity.
        braked_for_loss = False
        if loss_start is not None and now - last_moving < 2.2 and now - loss_start < 2.2:
            pedal = "brake"
            braked_for_loss = True
        margin = float(sim.map_margin(vehicle))
        s, xte = visual.locate_progress(p - visual.origin)
        count_key = status
        counts[count_key] += 1
        decision = time.perf_counter()
        rows.append(
            dict(
                t=now,
                camera=camera,
                supports=supports,
                s=s,
                xy=p[:2].tolist(),
                actual_cross_track=xte,
                yaw=angle,
                margin=margin,
                actual_velocity=velocity,
                position_error=float(np.linalg.norm(found - p)) if found is not None else None,
                reason=plan["reason"],
                source=count_key,
                search_ms=search_ms,
                recovery_status=reason_surface,
                stationary_evidence=still_evidence,
                steering=float(plan["steering"]),
                capture_ms=1000 * (frame_ready - captured),
                frame_to_command_ms=1000 * (decision - frame_ready),
                pedal=pedal,
                loss_brake=braked_for_loss,
                estimate=progress_estimate,
                camera_pan_deg=pan,
            )
        )
        writer(capture, rows[-1])
        if seq % 20 == 0:
            print(
                mode, scenario, seq, round(s, 1), status, reason_surface, plan["reason"], flush=True
            )
        if margin < 0.77:
            outcome = "left_static_clearance"
            break
        if driver.terminal is not None:
            outcome = driver.terminal[0]
            break
        if len(rows) > 80 and s - rows[-80]["s"] < 0.2:
            outcome = "no_progress"
            break
        dv = {"throttle": 2.15, "coast": -0.60, "brake": -4.7}[pedal]
        next_v = min(10.0, max(0.0, prior_v + dv * interval))
        projected_ds = 0.5 * (prior_v + next_v) * interval
        prior_s = min(visual.dist[-1], prior_s + projected_ds)
        prior_v = next_v
        for _ in range(10):
            dt = 0.02
            velocity = max(0.0, velocity + dv * dt)
            wheel += np.clip(1.6 * plan["steering"] - wheel, -2.5 * dt, 2.5 * dt)
            angle -= velocity * math.tan(wheel) * dt / 1.34
            vehicle[:2] += velocity * dt * np.array([math.cos(angle), math.sin(angle)])
            min_substep_clearance = min(min_substep_clearance, float(sim.map_margin(vehicle)))
            substep_count += 1
            if min_substep_clearance < 0.77:
                outcome = "left_static_clearance"
                break
        if outcome == "left_static_clearance":
            break
        ground, _ = visual.locate_progress(vehicle + sim.base - visual.origin)
        vehicle[2] = float(np.interp(ground, sim.g[:, 3], sim.g[:, 2])) + 1.48 - sim.base[2]
    report = dict(
        scope="kinematic simulation; RGB is the sole source of estimated pose and speed; CPU cost separated from virtual clock",
        mode=mode,
        scenario=scenario,
        outcome=outcome,
        independent_renderer="browser-webgl",
        indexed=bool(indexed),
        patches=bool(patches),
        endpoint_error=float(np.linalg.norm(vehicle[:2] + sim.base[:2] - sim.g[-1, :2])),
        frame_to_command_p95_ms=float(np.percentile([x["frame_to_command_ms"] for x in rows], 95)),
        seconds=now,
        distance_units=rows[-1]["s"],
        route_length=float(visual.dist[-1]),
        frame_count=len(rows),
        sources=dict(counts),
        stationary_rechecks=reset_count,
        brake_frames=sum(x["loss_brake"] for x in rows),
        tracks=bool(tracks),
        accepted_error_over_one=sum(
            x["position_error"] is not None and x["position_error"] > 1 for x in rows
        ),
        floor_margin=min(x["margin"] for x in rows),
        minimum_substep_clearance=min_substep_clearance,
        substep_count=substep_count,
        vision_cpu_p95_ms=float(np.percentile([x["search_ms"] for x in rows], 95)),
        elapsed_wall_seconds=time.perf_counter() - clock,
        observations=rows,
    )
    return report


def run(args):
    lab = args.lab.resolve()
    verified = json.loads((lab / "scooter5-verified-virtual-results.json").read_bytes())
    for name, key in verified["artifacts_sha256"].items():
        with (lab / name).open("rb") as handle:
            if file_digest(handle, "sha256").hexdigest() != key:
                raise ValueError("different fixture: " + name)
    original = sys.argv.copy()
    sys.path.insert(0, str(lab))
    try:
        sys.argv = [original[0], str(args.source)]
        import scooter5_visual_live_candidates_fast as visual

        sys.argv = [original[0], str(args.controller)]
        import scooter5_control_fixture as sim
    finally:
        sys.argv = original
    args.out.mkdir(parents=True, exist_ok=True)
    name = args.scenario + (
        "-tracked" if args.tracks else "-indexed" if args.indexed else "-classic"
    )
    if args.run_id and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,90}", args.run_id):
        raise ValueError("invalid run identifier")
    if args.patches and not args.bank:
        raise ValueError("reference patch mode requires the browser bank")
    if args.bank:
        name += "-browser-bank"
    if args.patches:
        name += "-patches"
    if args.run_id:
        name = args.run_id
    center = (visual.trace[:, :3].min(axis=0) + visual.trace[:, :3].max(axis=0)) * 0.5
    with (
        open_eye(
            args.port,
            center,
            width=sim.proto.profile.width,
            height=sim.proto.profile.height,
            hfov=visual.HFOV,
            browser=args.browser,
        ) as frame,
        av.open(str(args.out / (name + ".mp4")), "w", options={"movflags": "+faststart"}) as movie,
    ):
        stream = movie.add_stream("libx264", rate=5)
        stream.width = sim.proto.profile.width
        stream.height = sim.proto.profile.height
        stream.pix_fmt = "yuv420p"

        def writer(rgb, row):
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                movie.mux(packet)

        observer = (
            load_bank(args.bank, lab, visual, revision=frame.revision)
            if args.bank
            else IndexedLandmarks(visual)
            if args.indexed or args.tracks
            else None
        )
        patches = PatchReferences(args.bank, observer) if args.patches else None
        report = drive(sim, visual, frame, writer, args.scenario, observer, args.tracks, patches)
        report["placementRevision"] = frame.revision
        for packet in stream.encode():
            movie.mux(packet)
    if args.bank:
        with args.bank.open("rb") as handle:
            report["bank_sha256"] = file_digest(handle, "sha256").hexdigest()
    with (args.controller / "scripts/pilot/browser_route_lab/faggio_visual_pace.py").open(
        "rb"
    ) as handle:
        report["pace_code_sha256"] = file_digest(handle, "sha256").hexdigest()
    (args.out / (name + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({k: v for k, v in report.items() if k != "observations"}, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("lab", "source", "controller", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--port", type=int, default=8817)
    p.add_argument("--browser")
    p.add_argument("--patches", action="store_true")
    p.add_argument("--bank", type=Path)
    p.add_argument("--scenario", choices=("nominal", "shifted", "dim"), default="nominal")
    p.add_argument("--indexed", action="store_true")
    p.add_argument("--run-id")
    p.add_argument("--tracks", action="store_true")
    run(p.parse_args())
