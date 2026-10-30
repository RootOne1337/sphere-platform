"""Finite opt-in loopback live route observer. No native-input channel or model.

One manual start, one current in-memory JPEG, no frame archive/queue. Scene=active
is an explicit operator assumption, not an automatic game-state classifier.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import secrets
import threading
import time
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from motor_worker.policy import PolicyFrame
from motor_worker.route_localization import RouteLocalizer, SparseRoute
from motor_worker.session import HeadlessSession, SessionConfig
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.serve_route_trace_preview import Server

ROOT = Path(__file__).resolve().parents[2]


class LatestPreview:
    """A published result belongs to one fresh original RGB, never a FIFO."""

    def __init__(self, clock=time.perf_counter):
        self.clock, self.lock = clock, threading.Lock()
        self.value = None
        self.received = 0.0
        self.last_epoch, self.last_sequence = None, 0

    def publish(self, frame: PolicyFrame, result: dict):
        with self.lock:
            if not 0 <= self.clock() - frame.received_at <= 0.25:
                return False
            if (
                frame.capture_epoch == self.last_epoch
                and frame.receiver_sequence <= self.last_sequence
            ):
                return False
            self.last_epoch, self.last_sequence = frame.capture_epoch, frame.receiver_sequence
            self.value = {
                **result,
                "sequence": frame.receiver_sequence,
                "epoch": frame.capture_epoch,
            }
            self.received = frame.received_at
            return True

    def read(self):
        with self.lock:
            age = self.clock() - self.received
            if self.value is None or not 0 <= age <= 0.4:
                return None
            return {**self.value, "receiverAgeMs": age * 1000}

    def clear(self):
        with self.lock:
            self.value = None


def encode_preview(frame, pose, compute_ms):
    import cv2
    import numpy as np

    image = np.frombuffer(frame.rgb24, np.uint8).reshape(frame.height, frame.width, 3)
    image = cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA).copy()
    # Points were solved from this exact frame; drawing does not grant execution.
    if pose.state == "localized" and len(pose.polyline_px) >= 2:
        cv2.polylines(
            image,
            [np.rint(pose.polyline_px).astype(np.int32)],
            False,
            (80, 236, 218),
            2,
            cv2.LINE_AA,
        )
    ok, jpeg = cv2.imencode(
        ".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88]
    )
    if not ok or jpeg.nbytes > 512 * 1024:
        raise ValueError("live_preview_jpeg_bound")
    return dict(
        jpeg=base64.b64encode(jpeg).decode("ascii"),
        state=pose.state,
        reason=pose.reason,
        inliers=pose.inliers,
        medianReprojectionPx=pose.median_error_px,
        computeMs=compute_ms,
        segment=pose.segment,
        cameraTraceOnly=True,
        groundRoute=False,
        physicalActions=0,
    )


class Observer:
    def __init__(self, route, device, token, output, duration=120):
        self.route, self.device, self.token, self.output, self.duration = (
            route,
            device,
            token,
            output,
            duration,
        )
        self.preview = LatestPreview()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.used = False
        self.thread = None
        self.phase = "waiting_for_manual_start"
        self.tracker_kind = "descriptor"

    def start(self, hz, tracker_kind="descriptor"):
        with self.lock:
            if (self.used or type(hz) is not int or not 1 <= hz <= 10
                    or type(tracker_kind) is not str or tracker_kind not in {"descriptor", "anchored_flow"}):
                raise ValueError("observer_already_started_or_rate_invalid")
            if evaluate(collect(ROOT), min_ram_gib=12):
                raise ValueError("observer_resource_guard")
            self.used = True
            self.tracker_kind = tracker_kind
            self.phase = "connecting"
            self.thread = threading.Thread(
                target=lambda: asyncio.run(self.observe(hz)), daemon=True
            )
            self.thread.start()

    async def observe(self, hz):
        session = HeadlessSession(
            SessionConfig(
                "http://127.0.0.1:3015",
                self.device,
                duration=self.duration,
                observation_hz=hz,
                publish_rgb=True,
                probe_control=False,
                stun_url="stun:stun.cloudflare.com:3478",
            )
        )
        assert session.control is None and not session.config.probe_control
        running = asyncio.create_task(session.run(self.token))
        tracker = None
        sequence = 0
        counts, timings, methods, reasons = {}, [], Counter(), Counter()
        published, dropped = 0, 0
        episode, goal = str(uuid.uuid4()), str(uuid.uuid4())
        error = None
        try:
            while not running.done() and not self.stop.is_set():
                frame = session.read_rgb(after_sequence=sequence)
                if frame is None:
                    await asyncio.sleep(0.01)
                    continue
                if tracker is None or tracker.epoch != frame.capture_epoch:
                    tracker_class = RouteLocalizer
                    if self.tracker_kind == "anchored_flow":
                        from motor_worker.route_tracking import AnchoredRouteLocalizer

                        tracker_class = AnchoredRouteLocalizer
                    tracker = tracker_class(
                        self.route,
                        capture_epoch=frame.capture_epoch,
                        episode_id=episode,
                        goal_revision=goal,
                        clock=time.perf_counter,
                    )
                sequence = frame.receiver_sequence
                before = time.perf_counter()
                pose = await asyncio.to_thread(
                    tracker.observe, frame, episode_id=episode, goal_revision=goal, scene="active"
                )
                elapsed = (time.perf_counter() - before) * 1000
                counts[pose.state] = counts.get(pose.state, 0) + 1
                reason = pose.reason if type(pose.reason) is str else "unspecified"
                reasons[reason] += 1
                method = getattr(tracker, "last_diagnostic", {}).get("method", "descriptor_pnp")
                if type(method) is not str:
                    method = "unspecified"
                methods[method] += 1
                timings.append(elapsed)
                rendered = await asyncio.to_thread(encode_preview, frame, pose, elapsed)
                rendered["method"] = method
                if self.preview.publish(frame, rendered):
                    published += 1
                else:
                    dropped += 1
                self.phase = "observing_without_input"
            if not running.done():
                running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass
        except Exception as exc:
            error = type(exc).__name__
        finally:
            if not running.done():
                running.cancel()
                try:
                    await running
                except (Exception, asyncio.CancelledError):
                    pass
            await session.close()
            self.preview.clear()
            self.phase = "finished" if error is None else "failed"
            result = dict(
                scope="LIVE_ROUTE_OBSERVER_NOT_MOTOR_NAVIGATION",
                counts=counts,
                trackerKind=self.tracker_kind,
                methods=dict(methods),
                reasons=dict(reasons),
                previewsPublished=published,
                previewsExpiredOrSuperseded=dropped,
                computeMedianMs=sorted(timings)[len(timings) // 2] if timings else None,
                physicalActions=0,
                nativeInputChannelCreated=session.control is not None,
                framesArchived=0,
                modelLoaded=False,
                sceneIsOperatorAssumption=True,
                fullCaptureToModelLatencyKnown=False,
                error=error,
                transport=session.report(),
            )
            with self.output.open("x", encoding="utf-8") as file:
                json.dump(result, file, indent=2)


def serve(observer, port, state, seconds=1800):
    if state.exists() or not 1024 <= port <= 65535 or not 60 <= seconds <= 3600:
        raise ValueError("live_viewer_state_or_budget")
    prefix = "/" + secrets.token_urlsafe(24) + "/"
    origin = f"http://127.0.0.1:{port}"
    assets = Path(__file__).with_name("live_route_viewer")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def allowed(self):
            return self.headers.get("Host") == f"127.0.0.1:{port}" and self.path.startswith(prefix)

        def reply(self, code, value, content="application/json"):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            )
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            if not self.allowed():
                self.reply(404, {})
                return
            name = self.path[len(prefix) :]
            if name in ("", "viewer.js"):
                self.reply(
                    200,
                    (assets / ("index.html" if not name else name)).read_bytes(),
                    "text/html; charset=utf-8" if not name else "text/javascript; charset=utf-8",
                )
            elif name == "sample":
                value = observer.preview.read()
                self.reply(
                    200,
                    dict(
                        phase=observer.phase, sample=value, physicalActions=0, oneShot=observer.used,
                        trackersAvailable=["descriptor", "anchored_flow"], trackerKind=observer.tracker_kind,
                    ),
                )
            else:
                self.reply(404, {})

        def do_POST(self):
            if not self.allowed() or self.headers.get("Origin") != origin:
                self.reply(403, {})
                return
            if self.path not in (prefix + "start", prefix + "stop"):
                self.reply(404, {})
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or not 1 <= int(length) <= 128:
                self.reply(400, {})
                return
            try:
                data = json.loads(self.rfile.read(int(length)))
                if self.path == prefix + "stop":
                    if data != {}:
                        raise ValueError("invalid_stop")
                    observer.stop.set()
                else:
                    if (set(data) not in ({"hz", "sceneConfirmed"}, {"hz", "sceneConfirmed", "tracker"})
                            or data["sceneConfirmed"] is not True):
                        raise ValueError("operator_scene_confirmation_required")
                    observer.start(data["hz"], data.get("tracker", "descriptor"))
                self.reply(200, dict(phase=observer.phase))
            except (ValueError, TypeError, KeyError):
                self.reply(409, dict(error="observer_start_refused"))

    with Server(("127.0.0.1", port), Handler) as server:
        server.timeout = 1
        with state.open("x", encoding="utf-8") as file:
            json.dump(
                dict(pid=os.getpid(), url=origin + prefix, seconds=seconds, physicalActions=0), file
            )
        print(
            json.dumps(dict(ready=True, url=origin + prefix, state="waiting_for_manual_start")),
            flush=True,
        )
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                server.handle_request()
        finally:
            observer.stop.set()
            if observer.thread:
                observer.thread.join(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("map", "sha256", "device", "state", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--port", type=int, default=3350)
    parser.add_argument("--opencv-threads", type=int, default=4)
    args = parser.parse_args()
    token = os.environ.get("SPHERE_ACCESS_TOKEN", "")
    if (not token or Path(args.output).exists() or not 1 <= args.opencv_threads <= 8):
        raise ValueError("observer_token_missing_or_output_exists")
    import cv2

    cv2.setNumThreads(args.opencv_threads)
    route = SparseRoute.load(args.map, sha256=args.sha256)
    logging.disable(logging.CRITICAL)
    serve(Observer(route, args.device, token, Path(args.output)), args.port, Path(args.state))


if __name__ == "__main__":
    main()
