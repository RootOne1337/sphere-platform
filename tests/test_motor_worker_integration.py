"""Real local H.264/DTLS/SCTP with a fake APK, no external server or device.

Run in the isolated requirements-motor-worker environment. Tests are skipped in
the ordinary backend environment which does not own media dependencies.
"""

import asyncio
import importlib.util
import json
import secrets
import sys
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from motor_worker.pointer_probe import PointerProbe, ProbePoint
from motor_worker.policy import ActionChunk, GamepadState, NeutralPolicy, PolicyResult
from motor_worker.process_policy import ProcessPolicy, ProcessPolicyConfig
from motor_worker.session import HeadlessSession, SessionConfig
from motor_worker.stick_execution import StickPolicySession, StickProfile
from motor_worker.virtual_stick import StickGeometry

AVAILABLE = all(importlib.util.find_spec(m) for m in ["aiortc", "av", "websockets", "numpy"])
DEVICE = "753fd530-2f19-4e5e-98ba-769863678141"


@unittest.skipUnless(AVAILABLE, "isolated motor runtime dependencies required")
class HeadlessIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from websockets.asyncio.server import serve

        self.peers = []
        self.received = []
        self.no_ready = False
        self.no_closed = False
        self.no_alive = False
        self.stop_video = False
        self.bad_binding = False
        self.allow_cancel_close = False
        self.server_media = False
        self.foreign_readiness = False
        self.availability_state = None
        self.no_pointer_ack = False
        self.after_down = asyncio.Event()
        self.close_peer_on_goodbye = False
        self.close_peer_after_down = False
        self.server = await serve(self.endpoint, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*(p.close() for p in self.peers))

    async def endpoint(self, ws):
        if "/ws/stream/" in ws.request.path:
            auth = json.loads(await ws.recv())
            self.assertEqual(auth, {"token": "fixture-token", "delivery": "capture_only"})
            sid = secrets.token_hex(8)
            self.capture_identity = sid
            await ws.send(
                json.dumps(
                    {
                        "type": "stream_session",
                        "schema_version": 1,
                        "delivery": "capture_only",
                        "session_id": sid,
                    }
                )
            )
            packet = (
                b"\x02\x01"
                + bytes(8)
                + (4).to_bytes(4, "big")
                + bytes.fromhex(DEVICE.replace("-", ""))
                + b"\x00\x00\x01\x67"
            )
            if self.server_media:
                await ws.send(packet)
            await ws.send(
                json.dumps(
                    {
                        "type": "capture_ready",
                        "schema_version": 1,
                        "session_id": "0" * 16 if self.foreign_readiness else sid,
                        "width": 320,
                        "height": 180,
                    }
                )
            )
            async for raw in ws:
                d = json.loads(raw)
                if d.get("type") == "video_delivery":
                    self.received.append(d)
                    await ws.send(json.dumps({"type": "video_delivery_ack", "mode": "direct"}))
            return
        import numpy as np
        from aiortc import (
            RTCConfiguration,
            RTCPeerConnection,
            RTCSessionDescription,
            VideoStreamTrack,
        )
        from av import VideoFrame

        auth = json.loads(await ws.recv())
        offer = json.loads(await ws.recv())
        self.received.append({"authKeys": sorted(auth), "path": ws.request.path})
        if "history_session" in auth:
            self.assertEqual(auth["history_session"], self.capture_identity)
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers.append(peer)
        sid = secrets.token_hex(16)
        owner = secrets.token_hex(16)
        fixture = self

        class Camera(VideoStreamTrack):
            def __init__(self):
                super().__init__()
                self.index = 0

            async def recv(self):
                await asyncio.sleep(1 / 30)
                if fixture.stop_video and self.index > 15:
                    await asyncio.sleep(30)
                array = np.zeros((180, 320, 3), dtype=np.uint8)
                array[:] = [32, 96, 160]
                frame = VideoFrame.from_ndarray(array, format="rgb24")
                frame.pts = self.index * 3000
                frame.time_base = Fraction(1, 90000)
                self.index += 1
                return frame

        peer.addTrack(Camera())

        @peer.on("datachannel")
        def onchannel(channel):
            if channel.label == "sphere-video-v1":

                def opened():
                    channel.send(
                        f"SV1 {sid if not self.bad_binding else '0' * 32} {DEVICE} 320 180"
                    )

                if channel.readyState == "open":
                    opened()
                else:
                    channel.on("open", opened)

                @channel.on("message")
                def echo(raw):
                    channel.send(raw)
            else:

                def availability():
                    if fixture.availability_state:
                        channel.send(
                            json.dumps(
                                dict(
                                    type="input_availability",
                                    schema_version=1,
                                    session_id=sid,
                                    capture_epoch=DEVICE,
                                    revision=0,
                                    state=fixture.availability_state,
                                    task_id=None
                                    if fixture.availability_state == "manual"
                                    else "owned-task-1234",
                                )
                            )
                        )

                if channel.readyState == "open":
                    availability()
                else:
                    channel.on("open", availability)

                @channel.on("message")
                def control(raw):
                    d = json.loads(raw)
                    self.received.append(d)

                    def status(outcome, seq=0, action=4, gesture=0):
                        channel.send(
                            json.dumps(
                                dict(
                                    type="shared_input_status",
                                    session_id=sid,
                                    owner=owner,
                                    capture_epoch=DEVICE,
                                    sequence=seq,
                                    gesture=gesture,
                                    action=action,
                                    outcome=outcome,
                                    device_uptime_ms=int(time.monotonic() * 1000),
                                )
                            )
                        )

                    if d["type"] == "touch_open":
                        channel.send(
                            json.dumps(
                                dict(
                                    type="touch_session",
                                    session_id=sid,
                                    owner=owner,
                                    capture_epoch=DEVICE,
                                    frame_width=320,
                                    frame_height=180,
                                )
                            )
                        )
                        if not self.no_ready:
                            status("ready")
                    elif d["type"] == "touch_event":
                        if d["action"] == 0:
                            self.after_down.set()
                            if self.close_peer_after_down:
                                asyncio.create_task(peer.close())
                        if d["action"] == 4 and not self.no_alive:
                            status("alive", d["sequence"], gesture=d["gesture"])
                        elif d["action"] != 4 and not self.no_pointer_ack:
                            status("applied", d["sequence"], d["action"], d["gesture"])
                    elif d["type"] == "touch_close":
                        if not self.no_closed:
                            status("closed", action=3)

        await peer.setRemoteDescription(RTCSessionDescription(type="offer", sdp=offer["sdp"]))
        await peer.setLocalDescription(await peer.createAnswer())
        answer = (
            "\r\n".join(
                l
                for l in peer.localDescription.sdp.splitlines()
                if not l.startswith(("a=fingerprint:sha-384 ", "a=fingerprint:sha-512 "))
            )
            + "\r\n"
        )
        await ws.send(json.dumps(dict(type="direct_probe_answer", session_id=sid, sdp=answer)))
        from websockets.exceptions import ConnectionClosedError

        try:
            async for raw in ws:
                d = json.loads(raw)
                if d["type"] == "direct_probe_close":
                    if self.close_peer_on_goodbye:
                        await peer.close()
                    break
        except ConnectionClosedError:
            if not self.allow_cancel_close:
                raise

    async def test_real_h264_and_control_admission_without_game_actions(self):
        session = HeadlessSession(
            SessionConfig(
                self.url, DEVICE, duration=1.2, probe_control=True, capture_lifecycle=False
            )
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertGreater(report["decodedFrames"], 10)
        self.assertGreaterEqual(report["rgbObservations"], 4)
        self.assertEqual(report["route"]["path"], "host")
        self.assertTrue(report["control"]["nativeAdmissionConfirmed"])
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertFalse(report["control"]["nativeActionAppliedVerified"])
        self.assertGreater(report["workerScheduler"]["tickCount"], 10)
        self.assertGreater(report["workerScheduler"]["maxTickGapMs"], 0)
        self.assertTrue(report["control"]["rttTail"])
        self.assertEqual(report["control"]["rttTail"][0]["kind"], "alive")
        self.assertTrue(all(x.get("action", 4) == 4 for x in self.received))
        mean = report["observationTail"][-1]["rgbMean"]
        for expected, actual in zip([32, 96, 160], mean):
            self.assertLess(abs(expected - actual), 5)
        self.assertEqual(session.peer.connectionState, "closed")
        self.assertFalse(session.tasks)
        self.assertGreater(report["sctpTransport"]["dataChunksReceived"], 0)
        self.assertFalse(report["sctpTransport"]["timersAndReliabilityChanged"])

    async def test_video_only_does_not_open_input(self):
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=1, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertFalse(report["control"]["requested"])
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

    async def test_learned_boundary_holds_one_native_contact_and_confirms_cleanup(self):
        self.availability_state = "manual"

        class ForwardFixture:
            async def predict(self, request):
                await asyncio.sleep(.03)
                state = GamepadState((0, 1), (0, 0), GamepadState.neutral().buttons)
                return PolicyResult(request.request_id, request.frame.capture_epoch,
                                    request.frame.receiver_sequence, ActionChunk((state,) * 18, 60))

        session = StickPolicySession(
            SessionConfig(self.url, DEVICE, duration=1.4, probe_control=True,
                          capture_lifecycle=False, shadow_policy=True),
            profile=StickProfile(StickGeometry(320, 180, 60, 130, 20), "gamepad_left"),
            policy=ForwardFixture(), scene_guard=lambda frame: True, execution_enabled=True,
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        points = [d for d in self.received if d.get("type") == "touch_event" and d["action"] != 4]
        self.assertEqual([d["action"] for d in points], [0, 2, 1])
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertTrue(report["control"]["nativeActionAppliedVerified"])
        self.assertEqual(report["stickExecution"]["nativeApplied"], len(points))
        self.assertGreaterEqual(report["stickExecution"]["acceptedResults"], 3)
        self.assertTrue(report["stickExecution"]["quiescing"])
        self.assertEqual(report["policyShadow"]["physicalActionsSent"], len(points))

    async def test_unknown_game_scene_never_executes_model_actions(self):
        self.availability_state = "manual"
        session = StickPolicySession(
            SessionConfig(self.url, DEVICE, duration=1, probe_control=True,
                          capture_lifecycle=False, shadow_policy=True),
            profile=StickProfile(StickGeometry(320, 180, 60, 130, 20), "gamepad_left"),
            policy=NeutralPolicy(), scene_guard=lambda frame: False, execution_enabled=True,
        )
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["stickExecution"]["physicalEvents"], 0)
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertGreater(report["stickExecution"]["sceneRefusals"], 0)

    async def test_inference_over_one_sample_period_does_not_halve_rate_or_reengage(self):
        self.availability_state = "manual"

        class SlightlySlowFixture:
            async def predict(self, request):
                await asyncio.sleep(.21)
                state = GamepadState((0, 1), (0, 0), GamepadState.neutral().buttons)
                return PolicyResult(request.request_id, request.frame.capture_epoch,
                                    request.frame.receiver_sequence, ActionChunk((state,) * 18, 60))

        session = StickPolicySession(
            SessionConfig(self.url, DEVICE, duration=1.8, probe_control=True,
                          capture_lifecycle=False, shadow_policy=True),
            profile=StickProfile(StickGeometry(320, 180, 60, 130, 20), "gamepad_left"),
            policy=SlightlySlowFixture(), scene_guard=lambda frame: True, execution_enabled=True,
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        actions = [d["action"] for d in self.received
                   if d.get("type") == "touch_event" and d["action"] != 4]
        self.assertEqual(actions, [0, 2, 1])
        self.assertGreaterEqual(report["policyShadow"]["accepted"], 7)
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertLessEqual(max(s["receiverAgeAtResultMs"]
                                 for s in report["policyShadow"]["samples"]), 400)

    async def test_real_original_rgb_shadow_policy_has_no_physical_input(self):
        checked = []
        original = NeutralPolicy.predict

        async def inspect_rgb(provider, req):
            import numpy as np

            self.assertEqual((req.frame.width, req.frame.height), (320, 180))
            rgb = np.frombuffer(req.frame.rgb24, dtype=np.uint8).reshape(180, 320, 3)
            self.assertTrue(np.all(np.abs(rgb.mean(axis=(0, 1)) - [32, 96, 160]) < 5))
            checked.append(req.frame.receiver_sequence)
            return await original(provider, req)

        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, shadow_policy=True))
        with patch.object(NeutralPolicy, "predict", inspect_rgb):
            report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertGreaterEqual(len(checked), 2)
        self.assertEqual(report["kind"], "HEADLESS_POLICY_SHADOW_NOT_GAMEPLAY")
        self.assertGreaterEqual(report["policyShadow"]["accepted"], 2)
        self.assertTrue(report["policyShadow"]["cleanupConfirmed"])
        self.assertFalse(report["control"]["requested"])
        self.assertEqual(report["control"]["pointerKeyTextCommandsSent"], 0)
        self.assertFalse(any(d.get("type", "").startswith("touch_") for d in self.received))

    async def test_slow_shadow_policy_does_not_block_video_or_open_control(self):
        original = NeutralPolicy.predict

        async def slow(provider, req):
            await asyncio.sleep(0.3)
            return await original(provider, req)

        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, shadow_policy=True))
        with patch.object(NeutralPolicy, "predict", slow):
            report = await session.run("fixture-token")
        self.assertEqual(report["failure"], "policy_shadow_unconfirmed")
        self.assertGreater(report["decodedFrames"], 15)
        self.assertGreater(report["policyShadow"]["timedOut"], 0)
        self.assertTrue(report["policyShadow"]["cleanupConfirmed"])
        self.assertFalse(any(d.get("type", "").startswith("touch_") for d in self.received))

    async def test_h264_to_separate_process_preserves_shadow_only_and_closes_child(self):
        for adapter in ("nitrogen-decoded-v1", "open-p2p-150m-decoded-v1"):
            provider = ProcessPolicy(
                ProcessPolicyConfig(
                    Path(sys.executable).resolve(),
                    Path(__file__).with_name("motor_policy_child.py").resolve(),
                    adapter,
                    ("valid", adapter),
                )
            )
            await provider.start()
            session = HeadlessSession(
                SessionConfig(self.url, DEVICE, duration=1, shadow_policy=True),
                policy=provider,
                policy_timeout=0.75,
                policy_max_receiver_age=1,
            )
            try:
                report = await session.run("fixture-token")
                self.assertTrue(report["success"], report)
                self.assertGreater(report["policyShadow"]["accepted"], 0)
                self.assertGreater(report["decodedFrames"], 10)
                self.assertEqual(report["policyProcess"]["adapter"], adapter)
                self.assertIsNone(report["modelInstalled"])
                self.assertEqual(report["control"]["pointerKeyTextCommandsSent"], 0)
                self.assertFalse(report["control"]["requested"])
                self.assertEqual(report["captureLifecycle"]["serverBytesAfterHandover"], 0)
                self.assertTrue(report["policyShadow"]["cleanupConfirmed"])
            finally:
                await provider.close()
            self.assertTrue(provider.report()["cleanupConfirmed"])
        self.assertFalse(any(d.get("type", "").startswith("touch_") for d in self.received))

    async def test_slow_inference_does_not_freeze_an_old_rgb_frame_while_gpu_is_busy(self):
        session = None
        requests = []
        offered_while_busy = []

        class SlowGpu:
            async def predict(self, request):
                requests.append(request)
                before = session.shadow.offered
                await asyncio.sleep(0.35)
                offered_while_busy.append(session.shadow.offered - before)
                return await NeutralPolicy().predict(request)

        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=2, shadow_policy=True),
            policy=SlowGpu(),
            policy_timeout=0.75,
            policy_max_receiver_age=1,
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertGreaterEqual(len(requests), 3)
        self.assertEqual(offered_while_busy, [0] * len(offered_while_busy))
        self.assertEqual(report["policyShadow"]["replacedPending"], 0)
        self.assertGreater(report["decodedFrames"], 30)
        self.assertFalse(report["control"]["requested"])

    async def test_current_apk_availability_before_admission_does_not_break_media(self):
        self.availability_state = "manual"
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertEqual(report["control"]["availabilityState"], "manual")
        self.assertTrue(report["control"]["participantClosedConfirmed"])

    async def test_automation_availability_stops_before_asking_for_native_input(self):
        self.availability_state = "automation"
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertEqual(report["failure"], "control_unavailable_automation")
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

    def probe_config(self, *, width=320, duration=2, hold_ms=1000):
        return SessionConfig(
            self.url,
            DEVICE,
            duration=duration,
            probe_control=True,
            pointer_probe=PointerProbe(
                width,
                180,
                (
                    ProbePoint(0, 0, 120, 80),
                    ProbePoint(500, 2, 140, 80),
                    ProbePoint(hold_ms, 1, 140, 80),
                ),
            ),
        )

    async def test_real_media_pointer_hold_move_release_and_exact_native_receipts(self):
        self.availability_state = "manual"
        session = HeadlessSession(self.probe_config())
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertTrue(report["control"]["nativeActionAppliedVerified"])
        self.assertEqual(report["pointerProbe"]["appliedReceipts"], 3)
        events = [v for v in self.received if v.get("type") == "touch_event"]
        self.assertEqual([v["action"] for v in events if v["action"] != 4], [0, 2, 1])
        self.assertTrue(any(v["action"] == 4 and v["gesture"] == 1 for v in events))
        self.assertTrue(report["control"]["participantClosedConfirmed"])

    async def test_unknown_down_does_not_send_move_or_repeat_and_still_closes(self):
        self.availability_state = "manual"
        self.no_pointer_ack = True
        session = HeadlessSession(self.probe_config())
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertFalse(report["control"]["nativeActionAppliedVerified"])
        self.assertEqual(
            [
                v["action"]
                for v in self.received
                if v.get("type") == "touch_event" and v["action"] != 4
            ],
            [0],
        )
        self.assertTrue(report["control"]["participantClosedConfirmed"])

    async def test_probe_geometry_mismatch_never_opens_native_input(self):
        self.availability_state = "manual"
        session = HeadlessSession(self.probe_config(width=321))
        report = await session.run("fixture-token")
        self.assertEqual(report["failure"], "pointer_probe_geometry_mismatch")
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

    async def test_cancel_after_down_closes_participant_before_transport(self):
        self.availability_state = "manual"
        self.allow_cancel_close = True
        session = HeadlessSession(self.probe_config(duration=5, hold_ms=4000))
        task = asyncio.create_task(session.run("fixture-token"))
        async with asyncio.timeout(5):
            await self.after_down.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        report = session.report()
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertFalse(report["pointerProbe"]["complete"])
        self.assertEqual(
            [
                v["action"]
                for v in self.received
                if v.get("type") == "touch_event" and v["action"] != 4
            ],
            [0],
        )

    async def test_stalled_video_releases_held_input_without_waiting_for_next_point(self):
        self.availability_state = "manual"
        self.stop_video = True
        session = HeadlessSession(self.probe_config(duration=5, hold_ms=4000))
        report = await session.run("fixture-token")
        self.assertEqual(report["failure"], "pointer_probe_receiver_frame_stale")
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertFalse(report["pointerProbe"]["complete"])
        self.assertLess(report["durationObservedSeconds"], 2)

    async def test_remote_peer_close_after_confirmed_release_and_goodbye_is_not_loss(self):
        self.availability_state = "manual"
        self.close_peer_on_goodbye = True
        session = HeadlessSession(self.probe_config())
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertTrue(report["control"]["nativeActionAppliedVerified"])

    async def test_unexpected_peer_close_while_holding_still_fails(self):
        self.availability_state = "manual"
        self.close_peer_after_down = True
        session = HeadlessSession(self.probe_config())
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertIn(
            report["failure"],
            {"media_channel_closed", "control_channel_closed", "peer_disconnected"},
        )
        self.assertFalse(report["pointerProbe"]["complete"])

    async def test_lost_actor_receipt_fails_and_still_closes_participant(self):
        self.no_alive = True
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=2, probe_control=True, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["failure"], "control_alive_deadline")
        self.assertTrue(report["control"]["participantClosedConfirmed"])

    async def test_missing_close_is_not_reported_as_success(self):
        self.no_closed = True
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=1, probe_control=True, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertFalse(report["control"]["participantClosedConfirmed"])
        self.assertEqual(report["failure"], "control_close_unconfirmed")

    async def test_foreign_capture_binding_never_opens_input(self):
        self.bad_binding = True
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=1, probe_control=True, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["failure"], "invalid_capture_binding")
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

    async def test_capture_lifecycle_never_receives_server_media(self):
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertEqual(report["captureLifecycle"]["serverBootstrapBytesDiscarded"], 0)
        self.assertTrue(report["captureLifecycle"]["sourceReadinessConfirmed"])
        self.assertEqual(report["captureLifecycle"]["serverBytesAfterHandover"], 0)
        self.assertGreaterEqual(report["captureLifecycle"]["directDeliveryAcks"], 1)
        self.assertEqual(report["captureLifecycle"]["relayFramesDecoded"], 0)

    async def test_accidental_relay_fails_closed_before_opening_input(self):
        self.server_media = True
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["failure"], "server_media_forbidden")
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

    async def test_foreign_readiness_never_opens_direct_peer_or_input(self):
        self.foreign_readiness = True
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["failure"], "invalid_capture_readiness")
        self.assertFalse(self.peers)

    async def test_video_stall_ends_probe_and_closes_idle_input(self):
        self.stop_video = True
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=5, probe_control=True, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertFalse(report["success"])
        self.assertEqual(report["failure"], "video_frame_deadline")
        self.assertTrue(report["control"]["participantClosedConfirmed"])

    async def test_cancel_closes_admitted_participant_before_peer_retirement(self):
        self.allow_cancel_close = True
        session = HeadlessSession(
            SessionConfig(
                self.url, DEVICE, duration=10, probe_control=True, capture_lifecycle=False
            )
        )
        task = asyncio.create_task(session.run("fixture-token"))
        async with asyncio.timeout(5):
            while not session.admission or not session.admission.ready:
                await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        report = session.report()
        self.assertEqual(report["failure"], "cancelled")
        self.assertTrue(report["control"]["participantClosedConfirmed"])
        self.assertEqual(session.peer.connectionState, "closed")


if __name__ == "__main__":
    unittest.main()
