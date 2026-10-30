"""Explicit direct capture, strict inspection and offline visual-route compilation.

record never opens input. operator explicitly enables a human single-pointer
console and its native journal. No game launch/restart, render-quality change,
model download, autonomous motion or background monitor.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import uuid
from fractions import Fraction
from pathlib import Path

from motor_worker.landmarks import RouteViewMatcher, RouteViewProfile
from motor_worker.policy import PolicyFrame, epoch_valid, finite
from motor_worker.protocol import ProtocolError
from motor_worker.route_memory import TaughtRoute
from motor_worker.session import HeadlessSession, SessionConfig
from motor_worker.teach_capture import (
    TeachBudget,
    TeachCapture,
    capture_units,
    validate_capture,
    validate_inputs,
)


def inspect_capture(directory):
    manifest = validate_capture(directory)
    inputs = validate_inputs(directory, manifest)
    count, last_tick, last_received, max_gap = 0, 0, None, 0
    for metadata, _ in capture_units(directory, manifest):
        if last_received is not None:
            max_gap = max(max_gap, metadata["received_at"]-last_received)
        count += 1
        last_tick, last_received = metadata["rtp_ticks"], metadata["received_at"]
    return dict(complete=True, frames=count, media_seconds=last_tick/90000,
                mean_frame_hz=(count-1)*90000/last_tick if last_tick else 0,
                max_receiver_gap_ms=max_gap*1000, inputs=inputs, purpose=manifest["purpose"],
                geometry=[manifest["width"], manifest["height"]],
                source_capture_clock_mapping_known=False, execution_qualified=False)


def decoded_capture(directory, manifest):
    """Bounded decode, preserving recorded PTS lineage. Does not publish live RGB."""
    import av
    codec = av.CodecContext.create("h264", "r")
    codec.thread_count = 1
    codec.options = {"max_pixels": "8388608"}
    metadata_by_pts = {}
    decoded = 0

    def bind(frame):
        nonlocal decoded
        decoded += 1
        if ((frame.width, frame.height) != (manifest["width"], manifest["height"])
                or frame.pts not in metadata_by_pts):
            raise ProtocolError("route_decode_geometry_or_pts")
        return frame, metadata_by_pts.pop(frame.pts)

    try:
        for metadata, payload in capture_units(directory, manifest):
            packet = av.Packet(payload)
            packet.pts = packet.dts = metadata["rtp_ticks"]
            packet.time_base = Fraction(1, 90000)
            metadata_by_pts[packet.pts] = metadata
            if len(metadata_by_pts) > 32:
                raise ProtocolError("route_decode_pending_quota")
            for frame in codec.decode(packet):
                yield bind(frame)
        for frame in codec.decode(None):
            yield bind(frame)
    except av.FFmpegError:
        raise ProtocolError("route_video_decode_failed") from None
    if metadata_by_pts or decoded != manifest["frame_count"]:
        raise ProtocolError("route_decode_frame_count")


def compile_capture(directory, output, *, profile, world_revision, mode, interval=1.0):
    """Explicit offline frames, no laundering recorded pixels as live input."""
    if (type(profile) is not RouteViewProfile or not epoch_valid(world_revision)
            or type(mode) is not str or mode not in {"pedestrian", "vehicle"}
            or not finite(interval, 0.5, 10)):
        raise ProtocolError("invalid_route_compilation_profile")
    manifest = validate_capture(directory)
    validate_inputs(directory, manifest)
    if profile.width * manifest["height"] != profile.height * manifest["width"]:
        raise ProtocolError("route_aspect_change_requires_calibration")
    matcher = RouteViewMatcher(profile, clock=lambda: 0.0)  # Offline-only coordinate domain.
    views, ticks = [], []
    last_sampled = None
    decoded = 0
    for frame, meta in decoded_capture(directory, manifest):
        decoded += 1
        tick = meta["rtp_ticks"]
        if last_sampled is not None and tick-last_sampled < interval*90000:
            continue
        last_sampled = tick
        rgb = frame.reformat(width=profile.width, height=profile.height, format="rgb24").to_ndarray().tobytes()
        observation = PolicyFrame(manifest["capture_epoch"], meta["sequence"], 0.0, profile.width, profile.height, rgb)
        if views and matcher.compare(observation, (views[-1],)).status == "matched":
            continue  # Stationary repeated frames do not become a route.
        keyframe = matcher.learn(observation, keyframe_id=str(uuid.uuid4()))
        if keyframe is None:
            continue
        if len(views) == 64:
            raise ProtocolError("route_checkpoint_quota_split_demonstration")
        views.append(keyframe)
        ticks.append(tick)
    if len(views) < 2:
        raise ProtocolError("route_insufficient_distinct_views")
    route = TaughtRoute(str(uuid.uuid4()), world_revision, manifest["episode_id"], mode,
                       hashlib.sha256((Path(directory)/"manifest.json").read_bytes()).hexdigest(),
                       profile, tuple(views), tuple(ticks))
    route.save(output)
    return dict(route_id=route.id, checkpoints=len(views), decoded_frames=decoded,
                input_purpose=manifest["purpose"], runtime_geometry=[profile.width, profile.height],
                physical_execution_qualified=False, runtime_quality_qualified=False,
                source_capture_clock_mapping_known=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Finite read-only direct source H264 capture")
    operator = commands.add_parser("operator", help="Explicit human control and native input journal")
    operator.add_argument("--allow-native-input", action="store_true", required=True)
    operator.add_argument("--preview-hz", type=int, choices=[5, 10, 15, 20], default=5)
    for command in (record, operator):
        command.add_argument("--base-url", required=True)
        command.add_argument("--device", required=True)
        command.add_argument("--episode", required=True)
        command.add_argument("--profile-revision", required=True)
        command.add_argument("--seconds", type=float, default=30)
        command.add_argument("--max-mib", type=int, default=512)
        command.add_argument("--directory", type=Path, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--directory", type=Path, required=True)
    compile = commands.add_parser("compile")
    compile.add_argument("--directory", type=Path, required=True)
    compile.add_argument("--output", type=Path, required=True)
    compile.add_argument("--view-profile", type=Path, required=True)
    compile.add_argument("--world-revision", required=True)
    compile.add_argument("--mode", choices=["pedestrian", "vehicle"], required=True)
    compile.add_argument("--interval", type=float, default=1)
    quality = commands.add_parser("quality", help="Offline5Hz held-out view test; no physical input")
    quality.add_argument("--directory", type=Path, required=True)
    quality.add_argument("--route", type=Path, required=True)
    quality.add_argument("--render-scale", type=float, default=1)
    quality.add_argument("--jpeg-quality", type=int, default=100)
    quality.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    sink = None
    try:
        if args.command in {"record", "operator"}:
            token = os.environ.get("SPHERE_ACCESS_TOKEN", "")
            if not token:
                raise ProtocolError("missing_access_token")
            manual = args.command == "operator"
            config = SessionConfig(args.base_url, args.device, duration=args.seconds,
                                   probe_control=manual, publish_rgb=manual,
                                   observation_hz=args.preview_hz if manual else 5)
            if args.seconds > 285:
                raise ProtocolError("teach_duration_max285_with_setup_margin")
            # Source media starts before the monitor. Preserve an explicit15s
            # setup/teardown allowance without weakening the300s hard cap.
            budget = TeachBudget(duration=args.seconds+15, bytes=args.max_mib*1024*1024)
            # Capture has no model; preserve the existing host RAM/commit/disk guard.
            from scripts.pilot.resource_guard import collect, evaluate
            if evaluate(collect(args.directory.parent)):
                raise ProtocolError("teach_resource_guard")
            sink = TeachCapture(args.directory, device_id=args.device, episode_id=args.episode,
                                profile_revision=args.profile_revision, budget=budget)
            if manual:
                from motor_worker.teach_operator import LoopbackOperator, ManualTeachSession
                session = ManualTeachSession(config, recording=sink, native_input_enabled=args.allow_native_input)
                async def run_manual():
                    async with LoopbackOperator(session) as console:
                        print(json.dumps(dict(operator_url=console.url, human_control=True,
                                              autonomous=False, maximum_seconds=args.seconds)), flush=True)
                        return await session.run(token)
                report = asyncio.run(run_manual())
            else:
                session = HeadlessSession(config, recording=sink)
                report = asyncio.run(session.run(token))
            print(json.dumps(dict(success=report["success"], capture=report["teachingCapture"],
                                  route=report["route"], failure=report["failure"])))
            return 0 if report["success"] else 1
        elif args.command == "inspect":
            result = inspect_capture(args.directory)
        elif args.command == "quality":
            from motor_worker.route_quality import analyze_quality
            with args.output.open("x", encoding="utf-8", newline="\n") as dest:
                result = analyze_quality(args.directory, TaughtRoute.load(args.route),
                                         render_scale=args.render_scale, jpeg_quality=args.jpeg_quality)
                dest.write(json.dumps(result, indent=2)+"\n")
        else:
            with args.view_profile.open("rb") as source:
                raw = source.read(4097)
            profile = RouteViewProfile.parse(raw.decode("utf-8"))
            result = compile_capture(args.directory, args.output, profile=profile,
                                     world_revision=args.world_revision, mode=args.mode, interval=args.interval)
        print(json.dumps(dict(success=True, **result)))
        return 0
    except (ProtocolError, OSError, UnicodeError, KeyboardInterrupt, ImportError) as error:
        if sink is not None:
            sink.finish(transport_success=False, input_released=False)
        reason = str(error) if isinstance(error, ProtocolError) else (
            "teach_dependencies_missing" if isinstance(error, ImportError) else "teach_io_or_cancelled")
        print(json.dumps(dict(success=False, failure=reason)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
