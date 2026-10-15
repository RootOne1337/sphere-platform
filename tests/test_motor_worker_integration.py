"""Real local H.264/DTLS/SCTP with a fake APK, no external server or device.

Run in the isolated requirements-motor-worker environment. Tests are skipped in
the ordinary backend environment which does not own media dependencies.
"""

import asyncio
import importlib.util
import json
import secrets
import time
import unittest
from fractions import Fraction

from motor_worker.session import HeadlessSession, SessionConfig

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
        self.server = await serve(self.endpoint, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*(p.close() for p in self.peers))

    async def endpoint(self, ws):
        if "/ws/stream/" in ws.request.path:
            await ws.recv()  # Authentication fixture, deliberately not retained.
            sid = secrets.token_hex(8)
            self.capture_identity = sid
            await ws.send(json.dumps({"type": "stream_session", "session_id": sid}))
            packet = (
                b"\x02\x01"
                + bytes(8)
                + (4).to_bytes(4, "big")
                + bytes.fromhex(DEVICE.replace("-", ""))
                + b"\x00\x00\x01\x67"
            )
            await ws.send(packet)
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

                @channel.on("message")
                def control(raw):
                    d = json.loads(raw)
                    self.received.append(d)

                    def status(outcome, seq=0, action=4):
                        channel.send(
                            json.dumps(
                                dict(
                                    type="shared_input_status",
                                    session_id=sid,
                                    owner=owner,
                                    capture_epoch=DEVICE,
                                    sequence=seq,
                                    gesture=0,
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
                        if not self.no_alive:
                            status("alive", d["sequence"])
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
        self.assertTrue(all(x.get("action", 4) == 4 for x in self.received))
        mean = report["observationTail"][-1]["rgbMean"]
        for expected, actual in zip([32, 96, 160], mean):
            self.assertLess(abs(expected - actual), 5)
        self.assertEqual(session.peer.connectionState, "closed")
        self.assertFalse(session.tasks)

    async def test_video_only_does_not_open_input(self):
        session = HeadlessSession(
            SessionConfig(self.url, DEVICE, duration=1, capture_lifecycle=False)
        )
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertFalse(report["control"]["requested"])
        self.assertFalse(any(d.get("type") == "touch_open" for d in self.received))

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

    async def test_capture_lifecycle_bootstraps_then_acknowledges_direct_delivery(self):
        session = HeadlessSession(SessionConfig(self.url, DEVICE, duration=1, probe_control=True))
        report = await session.run("fixture-token")
        self.assertTrue(report["success"], report)
        self.assertEqual(report["captureLifecycle"]["serverBootstrapBytesDiscarded"], 34)
        self.assertEqual(report["captureLifecycle"]["serverBytesAfterHandover"], 0)
        self.assertGreaterEqual(report["captureLifecycle"]["directDeliveryAcks"], 1)
        self.assertEqual(report["captureLifecycle"]["relayFramesDecoded"], 0)

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
