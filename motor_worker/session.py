"""Finite headless video receiver, idle admission and opt-in pointer probe.

Uses existing authenticated signaling; no server-media fallback and no gameplay
profiles. One peer, one decoded-frame slot, one outstanding native receipt.
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
from motor_worker.pointer_probe import PointerProbe
from motor_worker.policy import NeutralPolicy, Policy, PolicyFrame, ShadowPolicyLoop
from motor_worker.process_policy import ProcessPolicy
from motor_worker.protocol import (
    ControlAdmission,
    InputAvailability,
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
    pointer_probe: PointerProbe | None = None
    shadow_policy: bool = False

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
        if (
            type(self.shadow_policy) is not bool
            or self.shadow_policy
            and self.pointer_probe is not None
        ):
            raise ProtocolError("invalid_shadow_policy_option")
        if self.stun_url is not None and self.stun_url != "stun:stun.cloudflare.com:3478":
            raise ProtocolError("invalid_stun_option")
        if self.pointer_probe is not None and (
            type(self.pointer_probe) is not PointerProbe
            or not self.probe_control
            or self.duration < self.pointer_probe.points[-1].at_ms / 1000 + 1
        ):
            raise ProtocolError("invalid_pointer_probe_budget")


def _rgb_sample(frame, include_original: bool = False) -> tuple[dict, bytes | None]:
    # This is an explicitly named pilot transform, not a validated model adapter.
    rgb = frame.reformat(width=256, height=256, format="rgb24").to_ndarray()
    sampled = {
        "rgbSha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
        "rgbMean": [round(float(v), 3) for v in rgb.mean(axis=(0, 1))],
    }
    original = None
    if include_original:
        if (
            not 1 <= frame.width <= 4096
            or not 1 <= frame.height <= 4096
            or frame.width * frame.height > 8 * 1024 * 1024
        ):
            raise ProtocolError("invalid_policy_frame")
        original = frame.to_ndarray(format="rgb24").tobytes()
    return sampled, original


class HeadlessSession:
    def __init__(
        self,
        config: SessionConfig,
        *,
        policy: Policy | None = None,
        policy_timeout: float = 0.25,
        policy_max_receiver_age: float = 0.5,
    ):
        if policy is not None and not config.shadow_policy:
            raise ProtocolError("external_policy_requires_shadow_mode")
        self.config = config
        self.peer = None
        self.ws = None
        self.media = None
        self.control = None
        self.binding: VideoBinding | None = None
        self.session: str | None = None
        self.admission: ControlAdmission | None = None
        self.availability: InputAvailability | None = None
        self.frames = LatestFrame()
        self.failure: str | None = None
        self.failed = asyncio.Event()
        self.closing = False
        self.retiring_transport = False
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
        self.capture_dimensions: tuple[int, int] | None = None
        self.capture_started = asyncio.Event()
        self.server_bootstrap_bytes = 0
        self.server_bytes_after_handover = 0
        self.handover_at: float | None = None
        self.handover_acks = 0
        self.receiver_stats: dict = {}
        self.task_failure: dict | None = None
        self.observations_at_start = 0
        self.decoded_at_start = 0
        self.probe_started_at: float | None = None
        self.probe_index = 0
        self.probe_samples: deque[dict] = deque(maxlen=64)
        self.shadow = (
            ShadowPolicyLoop(
                policy if policy is not None else NeutralPolicy(),
                timeout=policy_timeout,
                max_receiver_age=policy_max_receiver_age,
                # Owned process retirement has its own two-second bound. The
                # fixture's 100ms coroutine cancellation budget cannot attest
                # GPU-process cleanup. No new work runs while retirement waits.
                cleanup_timeout=2.5 if type(policy) is ProcessPolicy else 0.1,
            )
            if config.shadow_policy
            else None
        )

    def fail(self, reason: str) -> None:
        if not self.closing and self.failure is None:
            self.failure = reason
            self.failure_phase = self.phase
            self.failed.set()

    def _transport_closed(self, reason: str) -> None:
        # Remote peer close is expected only after the monitor has ended, the
        # native participant's cleanup was attempted and background senders stopped.
        # Cleanup errors themselves still go through fail(), preserving uncertainty.
        if not self.retiring_transport:
            self.fail(reason)

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
        from motor_worker.receiver import configure_h264_receiver

        self.h264_packet_buffer = configure_h264_receiver(receiver.receiver)
        self.media = self.peer.createDataChannel("sphere-video-v1", ordered=True)
        if self.config.probe_control:
            self.control = self.peer.createDataChannel("sphere-control-v2", ordered=True)
            self.control.on("message", self._control_message)
            self.control.on("close", lambda: self._transport_closed("control_channel_closed"))
        self.media.on("message", self._media_message)
        self.media.on("close", lambda: self._transport_closed("media_channel_closed"))

        @self.peer.on("connectionstatechange")
        def connection_state():
            if self.peer.connectionState in {"failed", "closed"}:
                self._transport_closed("peer_disconnected")

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
                    self.phase = "capture_start"
                    self.capture_ws = await stack.enter_async_context(
                        connect(
                            signaling_url(self.config.base_url, self.config.device_id).replace(
                                "/ws/direct-probe/", "/ws/stream/"
                            ),
                            max_size=4096,
                            max_queue=2,
                            open_timeout=8,
                            close_timeout=2,
                            proxy=None,
                        )
                    )
                    await self.capture_ws.send(
                        json.dumps({"token": token, "delivery": "capture_only"})
                    )
                    self.spawn(self._capture_messages())
                    async with asyncio.timeout(12):
                        ready = asyncio.create_task(self.capture_started.wait())
                        failed = asyncio.create_task(self.failed.wait())
                        try:
                            await asyncio.wait((ready, failed), return_when=asyncio.FIRST_COMPLETED)
                        finally:
                            ready.cancel()
                            failed.cancel()
                            await asyncio.gather(ready, failed, return_exceptions=True)
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
                self.availability = InputAvailability(self.session)
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
                if self.shadow:
                    self.spawn(self._shadow_policy())
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
                self.phase = "retiring_transport"
                self.retiring_transport = True
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
        """Read-only capture presence. No server media is accepted, even at startup."""
        async for raw in self.capture_ws:
            if isinstance(raw, bytes):
                if self.handover_at is not None:
                    self.server_bytes_after_handover += len(raw)
                else:
                    self.server_bootstrap_bytes += len(raw)
                raise ProtocolError("server_media_forbidden")
            data = message(raw)
            if data.get("type") == "stream_session":
                if (
                    self.capture_session is not None
                    or data.get("delivery") != "capture_only"
                    or data.get("schema_version") != 1
                    or not isinstance(data.get("session_id"), str)
                    or not re.fullmatch("[0-9a-f]{16}", data["session_id"])
                ):
                    raise ProtocolError("invalid_capture_session")
                self.capture_session = data["session_id"]
            elif data.get("type") == "capture_ready":
                if (
                    self.capture_dimensions is not None
                    or self.capture_session is None
                    or data.get("session_id") != self.capture_session
                    or data.get("schema_version") != 1
                    or set(data) != {"type", "schema_version", "session_id", "width", "height"}
                    or not integer(data.get("width"), 1, 8192)
                    or not integer(data.get("height"), 1, 8192)
                ):
                    raise ProtocolError("invalid_capture_readiness")
                self.capture_dimensions = (data["width"], data["height"])
                self.capture_started.set()
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
                if self.availability:
                    self.availability.bind(self.binding.epoch)
                if self.capture_dimensions is not None and self.capture_dimensions != (
                    self.binding.width,
                    self.binding.height,
                ):
                    raise ProtocolError("capture_changed_since_readiness")
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
            data = message(raw, 1024)
            if data.get("type") == "input_availability":
                if self.availability is None:
                    raise ProtocolError("missing_availability_session")
                self.availability.receive(data)
                if self.availability.state != "manual":
                    self.fail("control_unavailable_" + self.availability.state)
                return
            if self.admission is None:
                raise ProtocolError("unsolicited_control_message")
            self.admission.receive(raw, time.perf_counter())
            if self.admission.failure:
                self.fail(self.admission.failure)
            elif self.admission.closed and not self.admission.closing:
                self.fail("control_participant_revoked")
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
            if self.shadow and self.shadow.task is not None:
                # Do not freeze RGB while a slow GPU is busy. The decoder's
                # one latest-frame slot keeps advancing; select it only when
                # the next request can start. Never catch up old observations.
                await asyncio.sleep(0.005)
                continue
            before = time.perf_counter()
            item = self.frames.take(before) if self.binding else None
            if item:
                sampled, original = await asyncio.to_thread(
                    _rgb_sample, item.frame, self.shadow is not None
                )
                if self.shadow:
                    if self.shadow.epoch is None:
                        self.shadow.bind_epoch(self.binding.epoch)
                    self.shadow.offer(
                        PolicyFrame(
                            self.binding.epoch,
                            item.receiver_sequence,
                            item.received_at,
                            item.frame.width,
                            item.frame.height,
                            original,
                        )
                    )
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

    async def _shadow_policy(self) -> None:
        while not self.closing:
            await self.shadow.tick()
            await asyncio.sleep(0.01)

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
                probe = self.config.pointer_probe
                if probe and (probe.width, probe.height) != (
                    self.binding.width,
                    self.binding.height,
                ):
                    raise ProtocolError("pointer_probe_geometry_mismatch")
                self.admission = ControlAdmission(
                    self.session, self.binding, allow_pointer=probe is not None
                )
                self.open_sent = True
                self.control_open_at = now
                self._send_control(self.admission.open_message())
            if self.config.pointer_probe and self.admission and self.admission.ready:
                self._tick_pointer_probe(now)
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
                    if self.shadow and not self.shadow.accepted:
                        raise ProtocolError("policy_shadow_unconfirmed")
                    if self.config.pointer_probe and not self._probe_complete():
                        raise ProtocolError("pointer_probe_incomplete")
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

    def _probe_complete(self) -> bool:
        return bool(
            self.config.pointer_probe
            and self.admission
            and self.probe_index == len(self.config.pointer_probe.points)
            and self.admission.applied_receipts == self.probe_index
            and self.admission.pending_event is None
            and not self.admission.held
        )

    def _tick_pointer_probe(self, now: float) -> None:
        probe, control = self.config.pointer_probe, self.admission
        if not probe or not control:
            return
        if not self.availability or self.availability.state is None:
            return  # Legacy READY alone does not authorize this opt-in probe.
        if self.availability.state != "manual":
            raise ProtocolError("pointer_probe_input_unavailable")
        frame = self.frames.latest
        if control.held and (frame is None or not 0 <= now - frame.received_at <= 0.25):
            raise ProtocolError("pointer_probe_receiver_frame_stale")
        if self.probe_index == len(probe.points):
            return
        if self.probe_started_at is None:
            self.probe_started_at = now
        point = probe.points[self.probe_index]
        due = self.probe_started_at + point.at_ms / 1000
        if now < due:
            return
        if now - due > 0.1:
            raise ProtocolError("pointer_probe_schedule_missed")
        if control.pending is not None:
            return
        if frame is None or not 0 <= now - frame.received_at <= 0.25:
            raise ProtocolError("pointer_probe_receiver_frame_stale")
        packet = control.pointer(point.action, point.x, point.y, now)
        self.probe_index += 1
        self.probe_samples.append(
            dict(
                sequence=packet["sequence"],
                action=point.action,
                receiverSequence=frame.receiver_sequence,
                receiverFrameAgeMs=round((now - frame.received_at) * 1000, 3),
                scheduleLatenessMs=round((now - due) * 1000, 3),
            )
        )
        self._send_control(packet)

    def _send_control(self, packet: dict) -> None:
        if (
            not self.control
            or self.control.readyState != "open"
            or self.control.bufferedAmount > 1024
        ):
            raise ProtocolError("control_unavailable")
        self.control.send(json.dumps(packet, separators=(",", ":")))

    async def close_control(self) -> None:
        if self.admission and self.admission.closed:
            self.release_confirmed = True
            return
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
        if self.shadow:
            try:
                await self.shadow.close()
            except ProtocolError as exc:
                self.fail(str(exc))

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
            "kind": "HEADLESS_POLICY_SHADOW_NOT_GAMEPLAY"
            if self.shadow
            else "HEADLESS_POINTER_PROBE_NOT_GAMEPLAY"
            if self.config.pointer_probe
            else "HEADLESS_TRANSPORT_PILOT_NOT_GAMEPLAY",
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
                "delivery": "capture_only" if self.config.capture_lifecycle else "external",
                "sourceReadinessConfirmed": self.capture_dimensions is not None,
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
                "nativeActionAppliedVerified": self._probe_complete() and self.release_confirmed,
                "pointerKeyTextCommandsSent": control.pointer_commands if control else 0,
                "availabilityState": self.availability.state if self.availability else None,
            },
            "pointerProbe": {
                "requested": self.config.pointer_probe is not None,
                "expectedPoints": len(self.config.pointer_probe.points)
                if self.config.pointer_probe
                else 0,
                "attemptedPoints": self.probe_index,
                "appliedReceipts": control.applied_receipts if control else 0,
                "lastNativeActionRttMs": control.last_action_rtt_ms if control else None,
                "complete": self._probe_complete(),
                "samples": list(self.probe_samples),
            },
            "policyShadow": self.shadow.report() if self.shadow else {"enabled": False},
            "policyProcess": self.shadow.provider.report()
            if self.shadow and type(self.shadow.provider) is ProcessPolicy
            else None,
            "bounds": {"decodedFrameSlots": 1, "observationTailLimit": 64, "inputReplay": False},
            "limitations": [
                "No source capture frame ID/clock mapping: receiver age is not capture age.",
                "Unique RTP PTS is transport progress, not proof of fresh Android source pixels.",
                "Selected ICE pair proves a peer route, not LAN or VPN bypass.",
                "Idle ALIVE is actor liveness. Optional pointer ACKs prove dispatch, not game semantics or source-to-screen latency.",
                "User JWT pilot only; service identity, task delegation and model integration remain open.",
            ],
            # The external bridge verifies messages, not model weights. Its READY
            # is not proof of a learned model or correct RGB preprocessing.
            "modelInstalled": None
            if self.shadow and type(self.shadow.provider) is not NeutralPolicy
            else False,
            "h264PacketBuffer": self.h264_packet_buffer.report()
            if hasattr(self, "h264_packet_buffer")
            else None,
            "gameplayReady": False,
            "hardwareDecodeAssumed": False,
            "rgbTransform": "pilot_resize_256_square_rgb24_not_validated_model_preprocessing",
            "packages": {
                name: version(name) for name in ("aiortc", "aioice", "av", "websockets", "numpy")
            }
            if self.initialized
            else {},
        }
