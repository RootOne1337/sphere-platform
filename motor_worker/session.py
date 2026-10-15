"""Finite headless video receiver and optional idle control-admission probe.

Uses existing authenticated signaling; no server-media fallback and no gameplay
commands. One peer, one decoded-frame slot, one outstanding echo/idle receipt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
import time
from collections import deque
from contextlib import AsyncExitStack
from dataclasses import dataclass
from importlib.metadata import version

from motor_worker.observation import LatestFrame
from motor_worker.protocol import (
    ControlAdmission,
    ProtocolError,
    VideoBinding,
    integer,
    message,
    selected_route,
    signaling_url,
    validate_sdp,
    wire_offer,
)


@dataclass(frozen=True)
class SessionConfig:
    base_url: str
    device_id: str
    duration: float = 15
    observation_hz: float = 5
    probe_control: bool = False
    stun_url: str | None = None
    capture_lifecycle: bool = True

    def __post_init__(self) -> None:
        signaling_url(self.base_url, self.device_id)
        for value, low, high in ((self.duration, 1, 300), (self.observation_hz, 1, 20)):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ProtocolError("invalid_run_budget")
        if type(self.probe_control) is not bool or type(self.capture_lifecycle) is not bool:
            raise ProtocolError("invalid_control_option")
        if self.stun_url is not None and self.stun_url != "stun:stun.cloudflare.com:3478":
            raise ProtocolError("invalid_stun_option")


def _rgb_sample(frame) -> dict:
    # This is an explicitly named pilot transform, not a validated model adapter.
    rgb = frame.reformat(width=256, height=256, format="rgb24").to_ndarray()
    return {
        "rgbSha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
        "rgbMean": [round(float(v), 3) for v in rgb.mean(axis=(0, 1))],
    }


class HeadlessSession:
    def __init__(self, config: SessionConfig):
        self.config = config
        self.peer = None
        self.ws = None
        self.media = None
        self.control = None
        self.binding: VideoBinding | None = None
        self.session: str | None = None
        self.admission: ControlAdmission | None = None
        self.frames = LatestFrame()
        self.failure: str | None = None
        self.failed = asyncio.Event()
        self.closing = False
        self.tasks: list[asyncio.Task] = []
        self.pending_echo: tuple[str, float] | None = None
        self.echo_count = 0
        self.last_echo_rtt_ms: float | None = None
        self.samples: deque[dict] = deque(maxlen=64)
        self.route = {"path": "unknown", "lanProven": False}
        self.open_sent = False
        self.control_open_at: float | None = None
        self.track_count = 0
        self.sample_count = 0
        self.keepalive_count = 0
        self.monitor_seconds = 0.0
        self.release_confirmed = False
        self.cleanup_finished = False
        self.initialized = False
        self.phase = "created"
        self.failure_phase: str | None = None
        self.capture_ws = None
        self.capture_session: str | None = None
        self.capture_started = asyncio.Event()
        self.server_bootstrap_bytes = 0
        self.server_bytes_after_handover = 0
        self.handover_at: float | None = None
        self.handover_acks = 0
        self.receiver_stats: dict = {}
        self.task_failure: dict | None = None
        self.observations_at_start = 0
        self.decoded_at_start = 0

    def fail(self, reason: str) -> None:
        if not self.closing and self.failure is None:
            self.failure = reason
            self.failure_phase = self.phase
            self.failed.set()

    def spawn(self, coroutine) -> None:
        async def guarded():
            try:
                await coroutine
            except asyncio.CancelledError:
                raise
            except ProtocolError as exc:
                self.fail(str(exc))
            except Exception as exc:
                self.task_failure = {
                    "stage": coroutine.cr_code.co_name,
                    "exceptionType": type(exc).__name__,
                }
                self.fail("worker_task_failed")

        self.tasks.append(asyncio.create_task(guarded()))

    async def run(self, token: str) -> dict:
        if (
            not isinstance(token, str)
            or not 1 <= len(token) <= 8192
            or any(c.isspace() for c in token)
        ):
            raise ProtocolError("invalid_access_token")
        # Optional packages load only here, so pure protocol tests need no codecs.
        from aiortc import (
            RTCBundlePolicy,
            RTCConfiguration,
            RTCIceServer,
            RTCPeerConnection,
            RTCRtpReceiver,
            RTCSessionDescription,
        )
        from websockets.asyncio.client import connect

        self.peer = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[]
                if self.config.stun_url is None
                else [RTCIceServer(self.config.stun_url)],
                bundlePolicy=RTCBundlePolicy.MAX_BUNDLE,
            )
        )
        self.initialized = True
        # aiortc MAX_BUNDLE must allocate video before SCTP. Otherwise the
        # later video transport can be left without gathered local candidates.
        receiver = self.peer.addTransceiver("video", direction="recvonly")
        self.media = self.peer.createDataChannel("sphere-video-v1", ordered=True)
        if self.config.probe_control:
            self.control = self.peer.createDataChannel("sphere-control-v2", ordered=True)
            self.control.on("message", self._control_message)
            self.control.on("close", lambda: self.fail("control_channel_closed"))
        self.media.on("message", self._media_message)
        self.media.on("close", lambda: self.fail("media_channel_closed"))

        @self.peer.on("connectionstatechange")
        def connection_state():
            if self.peer.connectionState in {"failed", "closed"}:
                self.fail("peer_disconnected")

        @self.peer.on("track")
        def track_received(track):
            self.track_count += 1
            if track.kind != "video" or self.track_count != 1:
                self.fail("invalid_video_track")
                track.stop()
                return
            self.spawn(self._consume(track))

        codecs = [
            c
            for c in RTCRtpReceiver.getCapabilities("video").codecs
            if c.mimeType.lower() == "video/h264"
        ]
        if not codecs:
            self.fail("h264_unavailable")
        else:
            receiver.setCodecPreferences(codecs)
        try:
            if self.failure:
                return self.report()
            self.phase = "gathering"
            async with asyncio.timeout(8):
                await self.peer.setLocalDescription(await self.peer.createOffer())
            offer = wire_offer(self.peer.localDescription.sdp)
            async with AsyncExitStack() as stack:
                if self.config.capture_lifecycle:
                    self.phase = "capture_bootstrap"
                    self.capture_ws = await stack.enter_async_context(
                        connect(
                            signaling_url(self.config.base_url, self.config.device_id).replace(
                                "/ws/direct-probe/", "/ws/stream/"
                            ),
                            max_size=1024 * 1024 + 30,
                            max_queue=2,
                            open_timeout=8,
                            close_timeout=2,
                            proxy=None,
                        )
                    )
                    await self.capture_ws.send(json.dumps({"token": token}))
                    self.spawn(self._capture_messages())
                    async with asyncio.timeout(12):
                        await self.capture_started.wait()
                    if self.failure:
                        raise ProtocolError(self.failure)
                ws = await stack.enter_async_context(
                    connect(
                        signaling_url(self.config.base_url, self.config.device_id),
                        max_size=36864,
                        max_queue=4,
                        open_timeout=8,
                        close_timeout=2,
                        proxy=None,
                    )
                )
                self.ws = ws
                auth = {"token": token, "protocol": "sphere-video-v1", "trickle_ice": True}
                if self.capture_session:
                    auth["history_session"] = self.capture_session
                if self.config.probe_control:
                    auth.update(
                        control_session=self.capture_session or secrets.token_hex(8),
                        shared_control=True,
                    )
                await ws.send(json.dumps(auth))
                await ws.send(json.dumps({"type": "direct_probe_offer", "sdp": offer}))
                self.phase = "signaling_answer"
                async with asyncio.timeout(12):
                    answer = message(await ws.recv())
                if (
                    answer.keys() != {"type", "session_id", "sdp"}
                    or answer["type"] != "direct_probe_answer"
                    or not isinstance(answer["session_id"], str)
                    or not re.fullmatch(r"[0-9a-f]{32}", answer["session_id"])
                ):
                    raise ProtocolError("invalid_answer")
                self.session = answer["session_id"]
                self.phase = "remote_description"
                async with asyncio.timeout(5):
                    await self.peer.setRemoteDescription(
                        RTCSessionDescription(
                            type="answer", sdp=validate_sdp(answer["sdp"], offer=False)
                        )
                    )
                self.spawn(self._signaling())
                self.spawn(self._renew())
                self.spawn(self._observe())
                self.phase = "monitoring"
                try:
                    await self._monitor()
                except ProtocolError as exc:
                    # Preserve the primary failure before exiting the WS context;
                    # its 1011 close must not race in as a generic task failure.
                    self.fail(str(exc))
                except asyncio.CancelledError:
                    self.fail("cancelled")
                    raise
                finally:
                    # Keep signaling/media alive while the exact participant
                    # closes, including cancellation and application failures.
                    await self.close_control()
                    await self._stop_tasks()
                await ws.send('{"type":"direct_probe_close"}')
        except asyncio.CancelledError:
            self.fail("cancelled")
            raise
        except ProtocolError as exc:
            self.fail(str(exc))
        except TimeoutError:
            self.fail("setup_deadline")
        except Exception:
            self.fail("transport_unavailable")
        finally:
            await self.close()
        return self.report()

    async def _capture_messages(self) -> None:
        """Capture presence + explicit legacy-copy suppression, never decode relay."""
        async for raw in self.capture_ws:
            if isinstance(raw, bytes):
                if self.handover_at is not None:
                    self.server_bytes_after_handover += len(raw)
                else:
                    self.server_bootstrap_bytes += len(raw)
                if self.server_bootstrap_bytes > 8 * 1024 * 1024:
                    raise ProtocolError("capture_bootstrap_byte_budget")
                if self.server_bytes_after_handover > 1024 * 1024:
                    raise ProtocolError("server_copy_resumed")
                # A v2 encoded packet proves capture initialization, not pixels
                # seen by the model. Its bytes are counted then discarded.
                if (
                    len(raw) <= 30
                    or raw[0] != 2
                    or int.from_bytes(raw[10:14], "big") != len(raw) - 30
                ):
                    raise ProtocolError("invalid_bootstrap_frame")
                if self.capture_session:
                    self.capture_started.set()
                continue
            data = message(raw)
            if data.get("type") == "stream_session":
                if (
                    self.capture_session is not None
                    or not isinstance(data.get("session_id"), str)
                    or not re.fullmatch("[0-9a-f]{16}", data["session_id"])
                ):
                    raise ProtocolError("invalid_capture_session")
                self.capture_session = data["session_id"]
            elif data.get("type") == "video_delivery_ack":
                if data.get("mode") != "direct":
                    raise ProtocolError("invalid_delivery_ack")
                self.handover_at = self.handover_at or time.perf_counter()
                self.handover_acks += 1
            elif data.get("type") in {"video_delivery_error", "error"}:
                raise ProtocolError("capture_lifecycle_rejected")
            elif data.get("type") not in {"ping", "stream_link_ready"}:
                raise ProtocolError("unexpected_capture_message")
        self.fail("capture_lifecycle_closed")

    async def _promote_direct(self) -> None:
        if self.capture_ws:
            await self.capture_ws.send(
                json.dumps(
                    {"type": "video_delivery", "mode": "direct", "peer_session": self.session}
                )
            )

    async def _consume(self, track) -> None:
        while not self.closing:
            frame = await track.recv()
            if self.binding and (
                frame.width != self.binding.width or frame.height != self.binding.height
            ):
                raise ProtocolError("video_dimensions_changed")
            self.frames.put(frame, time.perf_counter())

    def _media_message(self, raw: object) -> None:
        try:
            if self.session is None:
                raise ProtocolError("missing_session_binding")
            if self.binding is None:
                self.binding = VideoBinding.parse(raw, self.session)
                if ((self.binding.width + 15) // 16) * ((self.binding.height + 15) // 16) > 8704:
                    raise ProtocolError("capture_exceeds_receiver_budget")
            elif self.pending_echo and raw == self.pending_echo[0]:
                self.echo_count += 1
                self.last_echo_rtt_ms = (time.perf_counter() - self.pending_echo[1]) * 1000
                self.pending_echo = None
            else:
                raise ProtocolError("invalid_echo_or_capture_change")
        except ProtocolError as exc:
            self.fail(str(exc))

    def _control_message(self, raw: object) -> None:
        try:
            if self.admission is None:
                raise ProtocolError("unsolicited_control_message")
            self.admission.receive(raw, time.perf_counter())
            if self.admission.failure:
                self.fail(self.admission.failure)
        except ProtocolError as exc:
            self.fail(str(exc))

    async def _signaling(self) -> None:
        from aiortc.sdp import candidate_from_sdp

        candidates = 0
        async for raw in self.ws:
            data = message(raw)
            ice = data.get("ice")
            if (
                data.keys() != {"type", "session_id", "ice"}
                or data["type"] != "direct_probe_candidate"
                or data["session_id"] != self.session
                or not isinstance(ice, dict)
                or ice.keys() != {"candidate", "sdpMid", "sdpMLineIndex"}
                or not isinstance(ice["candidate"], str)
                or len(ice["candidate"]) > 2048
                or not re.match(r"^candidate:\S+\s+[12]\s+udp\s+", ice["candidate"], re.I)
                or re.search(r"\btyp relay\b", ice["candidate"])
                or not isinstance(ice["sdpMid"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", ice["sdpMid"])
                or not integer(ice["sdpMLineIndex"], 0, 7)
                or candidates >= 64
            ):
                raise ProtocolError("invalid_remote_candidate")
            candidate = candidate_from_sdp(ice["candidate"][10:])
            candidate.sdpMid, candidate.sdpMLineIndex = ice["sdpMid"], ice["sdpMLineIndex"]
            await self.peer.addIceCandidate(candidate)
            candidates += 1
        self.fail("signaling_closed")

    async def _renew(self) -> None:
        while not self.closing:
            await asyncio.sleep(5)
            self.keepalive_count += 1
            await self.ws.send(
                json.dumps({"type": "direct_video_keepalive", "sequence": self.keepalive_count})
            )

    async def _observe(self) -> None:
        period = 1 / self.config.observation_hz
        next_at = time.perf_counter()
        while not self.closing:
            await asyncio.sleep(max(0, next_at - time.perf_counter()))
            before = time.perf_counter()
            item = self.frames.take(before) if self.binding else None
            if item:
                sampled = await asyncio.to_thread(_rgb_sample, item.frame)
                self.sample_count += 1
                self.samples.append(
                    {
                        "receiverSequence": item.receiver_sequence,
                        "rtpPts": item.pts,
                        "rtpTimeBase": str(item.time_base),
                        "decodedAgeAtSelectionMs": round((before - item.received_at) * 1000, 3),
                        "transformMs": round((time.perf_counter() - before) * 1000, 3),
                        **sampled,
                    }
                )
            next_at += period
            if next_at < time.perf_counter():
                next_at = time.perf_counter() + period  # No catch-up bursts of old observations.

    async def _monitor(self) -> None:
        started, active_at = time.perf_counter(), None
        heartbeat_at, echo_at, promote_at = 0.0, 0.0, 0.0
        while not self.failed.is_set():
            now = time.perf_counter()
            self.route = selected_route(self.peer)
            if self.route["path"] == "relay":
                raise ProtocolError("relay_not_admitted")
            if self.control and self.control.readyState == "open" and self.control_open_at is None:
                self.control_open_at = now
            fresh = (
                self.binding is not None
                and self.frames.latest is not None
                and now - self.frames.latest.received_at <= 1
            )
            if fresh and (
                self.frames.latest.frame.width != self.binding.width
                or self.frames.latest.frame.height != self.binding.height
            ):
                raise ProtocolError("video_dimensions_changed")
            media_ready = (
                fresh
                and self.media.readyState == "open"
                and self.peer.connectionState == "connected"
            )
            if media_ready and self.capture_ws and now - promote_at >= 3:
                await self._promote_direct()
                promote_at = now
            if (
                media_ready
                and self.control
                and self.control.readyState == "open"
                and not self.open_sent
            ):
                self.admission = ControlAdmission(self.session, self.binding)
                self.open_sent = True
                self.control_open_at = now
                self._send_control(self.admission.open_message())
            if self.admission and self.admission.ready and now - heartbeat_at >= 0.3:
                packet = self.admission.heartbeat(now)
                if packet:
                    self._send_control(packet)
                    heartbeat_at = now
            if (
                self.open_sent
                and self.admission
                and not self.admission.ready
                and now - self.control_open_at > 8
            ):
                raise ProtocolError("control_admission_deadline")
            if media_ready and (
                not self.config.probe_control or self.admission and self.admission.ready
            ):
                if active_at is None:
                    active_at = now
                    self.observations_at_start = self.sample_count
                    self.decoded_at_start = self.frames.decoded
                self.monitor_seconds = now - active_at
            if active_at is None and now - started >= 15:
                raise ProtocolError("video_or_control_setup_deadline")
            if active_at is not None:
                if self.frames.latest is None or now - self.frames.latest.received_at > 3:
                    raise ProtocolError("video_frame_deadline")
                if self.monitor_seconds >= self.config.duration:
                    if self.sample_count <= self.observations_at_start or self.echo_count < 1:
                        raise ProtocolError("observation_or_echo_unconfirmed")
                    if self.config.probe_control and (
                        not self.admission or self.admission.alive_receipts < 1
                    ):
                        raise ProtocolError("control_alive_unconfirmed")
                    if self.capture_ws and not self.handover_acks:
                        raise ProtocolError("direct_delivery_unconfirmed")
                    if self.route["path"] == "unknown":
                        raise ProtocolError("selected_route_unverified")
                    return
            if self.media.readyState == "open" and self.binding and now - echo_at >= 5:
                if self.pending_echo is not None:
                    raise ProtocolError("echo_deadline")
                raw = f"SL1 {self.session} {self.echo_count + 1}"
                if self.media.bufferedAmount > 1024:
                    raise ProtocolError("media_backpressure")
                self.pending_echo = raw, now
                self.media.send(raw)
                echo_at = now
            await asyncio.sleep(0.02)

    def _send_control(self, packet: dict) -> None:
        if (
            not self.control
            or self.control.readyState != "open"
            or self.control.bufferedAmount > 1024
        ):
            raise ProtocolError("control_unavailable")
        self.control.send(json.dumps(packet, separators=(",", ":")))

    async def close_control(self) -> None:
        if self.admission and not self.admission.closing:
            try:
                self._send_control(self.admission.close_message())
                async with asyncio.timeout(2):
                    while not self.admission.closed:
                        await asyncio.sleep(0.02)
                self.release_confirmed = True
            except (TimeoutError, ProtocolError):
                self.fail("control_close_unconfirmed")

    async def _stop_tasks(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def close(self) -> None:
        if self.cleanup_finished:
            return
        try:
            await self.close_control()
        finally:
            self.closing = True
            await self._stop_tasks()
            if self.peer:
                try:
                    async with asyncio.timeout(1):
                        stats = await self.peer.getStats()
                    for item in stats.values():
                        if item.type == "inbound-rtp" and item.kind == "video":
                            self.receiver_stats = {
                                k: getattr(item, k, None)
                                for k in ("packetsReceived", "packetsLost", "jitter")
                            }
                except (TimeoutError, AttributeError):
                    pass
                try:
                    async with asyncio.timeout(3):
                        await self.peer.close()
                except (TimeoutError, OSError):
                    # Preserve uncertainty; report cannot attest resource cleanup.
                    if self.failure is None:
                        self.failure = "peer_cleanup_unconfirmed"
                        self.failure_phase = "cleanup"
                    return
            self.cleanup_finished = True

    def report(self) -> dict:
        cap = self.binding
        control = self.admission
        return {
            "schemaVersion": 1,
            "kind": "HEADLESS_TRANSPORT_PILOT_NOT_GAMEPLAY",
            "deviceId": self.config.device_id,
            "success": self.failure is None
            and self.monitor_seconds >= self.config.duration
            and self.cleanup_finished,
            "failure": self.failure,
            "failurePhase": self.failure_phase,
            "taskFailure": self.task_failure,
            "durationObservedSeconds": round(self.monitor_seconds, 3),
            "requestedObservationHz": self.config.observation_hz,
            "localTimingClock": "perf_counter",
            "decodedFrames": self.frames.decoded,
            "receiverStats": self.receiver_stats,
            "h264ReceiveLevel": 42,
            "duplicateOrReorderedPts": self.frames.duplicate_or_reordered_pts,
            "rgbObservations": self.sample_count,
            "rgbObservationsDuringMonitor": max(0, self.sample_count - self.observations_at_start),
            "observationHzDuringMonitor": round(
                (self.sample_count - self.observations_at_start) / self.monitor_seconds, 3
            )
            if self.monitor_seconds
            else None,
            "decodedFpsDuringMonitor": round(
                (self.frames.decoded - self.decoded_at_start) / self.monitor_seconds, 3
            )
            if self.monitor_seconds
            else None,
            "observationTail": list(self.samples),
            "capture": None
            if cap is None
            else {"epoch": cap.epoch, "width": cap.width, "height": cap.height},
            "route": self.route,
            "videoEchoReceipts": self.echo_count,
            "lastEchoRttMs": self.last_echo_rtt_ms,
            "signalingRenewalsSent": self.keepalive_count,
            "captureLifecycle": {
                "requested": self.config.capture_lifecycle,
                "directDeliveryAcks": self.handover_acks,
                "serverBootstrapBytesDiscarded": self.server_bootstrap_bytes,
                "serverBytesAfterHandover": self.server_bytes_after_handover,
                "relayFramesDecoded": 0,
            },
            "control": {
                "requested": self.config.probe_control,
                "dataChannelOpened": self.control_open_at is not None,
                "nativeAdmissionConfirmed": bool(control and control.ever_ready),
                "actorAliveReceipts": control.alive_receipts if control else 0,
                "lastActorRttMs": control.last_actor_rtt_ms if control else None,
                "participantClosedConfirmed": self.release_confirmed,
                "nativeActionAppliedVerified": False,
                "pointerKeyTextCommandsSent": 0,
            },
            "bounds": {"decodedFrameSlots": 1, "observationTailLimit": 64, "inputReplay": False},
            "limitations": [
                "No source capture frame ID/clock mapping: receiver age is not capture age.",
                "Unique RTP PTS is transport progress, not proof of fresh Android source pixels.",
                "Selected ICE pair proves a peer route, not LAN or VPN bypass.",
                "Idle ALIVE is APK actor liveness; no native gameplay action was executed.",
                "User JWT pilot only; service identity, task delegation and model integration remain open.",
            ],
            "modelInstalled": False,
            "gameplayReady": False,
            "hardwareDecodeAssumed": False,
            "rgbTransform": "pilot_resize_256_square_rgb24_not_validated_model_preprocessing",
            "packages": {
                name: version(name) for name in ("aiortc", "aioice", "av", "websockets", "numpy")
            }
            if self.initialized
            else {},
        }
