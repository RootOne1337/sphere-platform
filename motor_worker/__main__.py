"""Finite CLI. Token is accepted only from the environment, never argv/output."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from motor_worker.minimap import MinimapProfile, MinimapRouteShadow
from motor_worker.pointer_probe import PointerProbe
from motor_worker.protocol import ProtocolError
from motor_worker.session import HeadlessSession, SessionConfig


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Direct APK video, idle admission or opt-in finite pointer probe. No model."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--observation-hz", type=float, default=5)
    parser.add_argument(
        "--shadow-policy",
        choices=["neutral", "minimap"],
        help="Read-only neutral fixture or calibrated minimap analysis; sends no actions",
    )
    parser.add_argument("--minimap-profile", type=Path, help="Version1 minimap profile JSON, max4096B")
    parser.add_argument("--goal-revision", help="Optional UUID identifying this minimap analysis goal")
    parser.add_argument(
        "--probe-control",
        action="store_true",
        help="Confirm native admission; idle only unless --pointer-probe is also supplied",
    )
    parser.add_argument("--stun", choices=["stun:stun.cloudflare.com:3478"])
    parser.add_argument(
        "--pointer-probe",
        type=Path,
        help="Opt-in real single-finger path JSON, max5s/64points; requires --probe-control",
    )
    parser.add_argument(
        "--existing-capture",
        action="store_true",
        help="Do not register capture presence; requires capture kept alive elsewhere",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--snapshot", type=Path, help="Optional one final decoded PNG; no continuous recording"
    )
    args = parser.parse_args()
    # Network libraries may log private candidates / remote close reasons. The CLI
    # emits only our finite structured report and fixed errors.
    logging.disable(logging.CRITICAL)
    try:
        observer = None
        if args.shadow_policy == "minimap":
            if args.minimap_profile is None or args.probe_control or args.pointer_probe:
                raise ProtocolError("invalid_minimap_shadow_options")
            if any(importlib.util.find_spec(name) is None for name in ("cv2", "numpy")):
                raise ProtocolError("motor_vision_dependencies_missing")
            try:
                # Load optional native libraries before starting the video clock.
                importlib.import_module("cv2")
                importlib.import_module("numpy")
            except ImportError as exc:
                raise ProtocolError("motor_vision_dependencies_missing") from exc
            try:
                with args.minimap_profile.open("rb") as source:
                    raw_profile = source.read(4097)
            except OSError as exc:
                raise ProtocolError("minimap_profile_file_unavailable") from exc
            try:
                profile = MinimapProfile.parse(raw_profile.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ProtocolError("invalid_minimap_profile_encoding") from exc
            observer = MinimapRouteShadow(profile, goal_revision=args.goal_revision or str(uuid.uuid4()))
        elif args.minimap_profile is not None or args.goal_revision is not None:
            raise ProtocolError("invalid_minimap_shadow_options")
        probe = None
        if args.pointer_probe:
            try:
                with args.pointer_probe.open("rb") as source:
                    raw = source.read(16385)
            except OSError as exc:
                raise ProtocolError("pointer_probe_file_unavailable") from exc
            try:
                probe = PointerProbe.parse(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ProtocolError("invalid_pointer_probe") from exc
        config = SessionConfig(
            args.base_url,
            args.device,
            args.seconds,
            args.observation_hz,
            args.probe_control,
            args.stun,
            not args.existing_capture,
            probe,
            args.shadow_policy is not None,
        )
        token = os.environ.get("SPHERE_ACCESS_TOKEN", "")
        if not token:
            raise ProtocolError("missing_access_token")
        # Reserve output names before touching a device. Never overwrite a report,
        # directory, symlink or existing snapshot.
        with args.output.open("x", encoding="utf-8") as output:
            snapshot = None
            if args.snapshot:
                snapshot = args.snapshot.open("xb")
            session = HeadlessSession(config, policy=observer)

            async def run_session():
                try:
                    return await session.run(token)
                finally:
                    if observer:
                        await observer.close()

            try:
                try:
                    report = asyncio.run(run_session())
                except KeyboardInterrupt:
                    report = session.report()
                    report.update(success=False, failure="cancelled")
                except ImportError:
                    report = {"success": False, "failure": "motor_dependencies_missing"}
                if snapshot and session.frames.latest and session.binding:
                    session.frames.latest.frame.to_image().save(snapshot, format="PNG")
                output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            finally:
                if snapshot:
                    snapshot.close()
                session.frames.clear()
        print(
            json.dumps(
                {
                    k: report.get(k)
                    for k in (
                        "success",
                        "failure",
                        "decodedFrames",
                        "rgbObservations",
                        "control",
                        "route",
                    )
                },
                ensure_ascii=False,
            )
        )
        return 0 if report.get("success") else 1
    except (ProtocolError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ProtocolError) else "output_unavailable"
        print(json.dumps({"success": False, "failure": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
