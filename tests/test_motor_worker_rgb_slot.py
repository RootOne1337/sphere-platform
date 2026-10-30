import asyncio
import unittest
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import patch

from motor_worker.observation import LatestFrame
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError, VideoBinding
from motor_worker.session import HeadlessSession, SessionConfig

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
OTHER = "0b59dcba-444f-4daa-9a22-aa1b1294ed98"


class SharedRGBTests(unittest.TestCase):
    def setUp(self):
        self.session = HeadlessSession(SessionConfig("http://localhost:3015", EPOCH, publish_rgb=True))
        self.session.binding = VideoBinding(EPOCH, 2, 1)
        self.frame = PolicyFrame(EPOCH, 7, 1, 2, 1, b"\0" * 6)
        self.session.latest_rgb = self.frame
        self.clock = patch("motor_worker.session.time.perf_counter", return_value=1.1)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_two_consumers_share_one_immutable_frame_without_consuming_it(self):
        motor = self.session.read_rgb(after_sequence=6)
        perception = self.session.read_rgb(after_sequence=0)
        self.assertIs(motor, perception)
        self.assertIs(motor, self.frame)
        with self.assertRaises(FrozenInstanceError):
            motor.rgb24 = b"\xff" * 6
        self.assertIsNone(self.session.read_rgb(after_sequence=7))

    def test_slow_reader_gets_latest_slot_without_an_old_frame_queue(self):
        latest = replace(self.frame, receiver_sequence=100)
        self.session.latest_rgb = latest
        self.assertIs(self.session.read_rgb(after_sequence=1), latest)

    def test_wrong_epoch_geometry_future_clock_and_stale_payload_are_refused(self):
        for frame in (
            replace(self.frame, capture_epoch=OTHER),
            PolicyFrame(EPOCH, 8, 1, 1, 1, b"\0" * 3),
            replace(self.frame, received_at=1.2),
            replace(self.frame, received_at=0.8),
        ):
            self.session.latest_rgb = frame
            self.assertIsNone(self.session.read_rgb())

    def test_stopping_failing_or_disabled_session_cannot_publish_old_rgb(self):
        self.session.closing = True
        self.assertIsNone(self.session.read_rgb())
        self.session.closing = False
        self.session.retiring_transport = True
        self.assertIsNone(self.session.read_rgb())
        self.session.retiring_transport = False
        self.session.fail("video_frame_deadline")
        self.assertIsNone(self.session.read_rgb())
        self.session.failure = None
        self.session.config = replace(self.session.config, publish_rgb=False)
        self.assertIsNone(self.session.read_rgb())

    def test_invalid_budget_cannot_waive_receiver_freshness(self):
        for kwargs in ({"max_age": 10}, {"max_age": float("nan")},
                       {"after_sequence": True}, {"after_sequence": -1}):
            with self.assertRaises(ProtocolError):
                self.session.read_rgb(**kwargs)
        with self.assertRaises(ProtocolError):
            replace(self.session.config, publish_rgb=1)


class SharedRGBCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_clears_slot_without_opening_a_native_actor(self):
        session = HeadlessSession(SessionConfig("http://localhost:3015", EPOCH, publish_rgb=True))
        session.latest_rgb = PolicyFrame(EPOCH, 1, 1, 1, 1, b"\0" * 3)
        await session.close()
        self.assertIsNone(session.latest_rgb)
        self.assertIsNone(session.control)
        self.assertTrue(session.cleanup_finished)

    async def test_epoch_change_during_native_transform_cannot_relabel_old_pixels(self):
        session = HeadlessSession(SessionConfig("http://localhost:3015", EPOCH, publish_rgb=True))
        session.binding = VideoBinding(EPOCH, 1, 1)
        source = SimpleNamespace(pts=1, time_base=Fraction(1, 90000), width=1, height=1)
        session.frames.put(source, 1)

        def transform(*_):
            session.binding = VideoBinding(OTHER, 1, 1)
            return {"rgbSha256": "unused", "rgbMean": [0, 0, 0]}, b"\0" * 3

        with patch("motor_worker.session._rgb_sample", side_effect=transform):
            task = asyncio.create_task(session._observe())
            await asyncio.sleep(0.03)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertIsNone(session.latest_rgb)
        self.assertEqual(session.sample_count, 0)


class DecodedGapTests(unittest.TestCase):
    def test_only_unique_decoded_arrivals_count_and_clock_is_not_capture_latency(self):
        slot = LatestFrame()
        frame = SimpleNamespace(pts=1, time_base=Fraction(1, 90000))
        self.assertTrue(slot.put(frame, 1))
        self.assertFalse(slot.put(frame, 1.25))
        self.assertTrue(slot.put(SimpleNamespace(pts=2, time_base=frame.time_base), 1.6))
        self.assertAlmostEqual(slot.max_unique_arrival_gap_ms, 600)
        self.assertEqual(slot.unique_arrival_gaps_over_250ms, 1)
        self.assertIsNotNone(slot.take(1.6, max_age=0.25))
