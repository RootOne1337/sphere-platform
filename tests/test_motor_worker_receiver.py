"""A fragmented IDR larger than128 packets must reach the decoder intact."""

import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from motor_worker.protocol import ProtocolError
from motor_worker.receiver import configure_h264_receiver


@unittest.skipUnless(importlib.util.find_spec("aiortc"), "requires media runtime")
class H264ReceiverTests(unittest.TestCase):
    def test_large_access_unit_overflows_stock_buffer_but_survives_adapter(self):
        from aiortc.jitterbuffer import JitterBuffer
        from aiortc.rtp import RtpPacket

        receiver = SimpleNamespace(_RTCRtpReceiver__jitter_buffer=JitterBuffer(128, is_video=True))
        measured = configure_h264_receiver(receiver)
        old = JitterBuffer(128, is_video=True)
        old_pli = 0
        old_frames = []
        emitted = []
        # 300x1200 bytes is an ordinary high-detail IDR, below APK's1MiB cap.
        for i in range(301):
            packet = RtpPacket(sequence_number=i, timestamp=1000 if i < 300 else 2000)
            packet._data = bytes([i % 251]) * 1200
            pli, old_frame = old.add(packet)
            if old_frame:
                old_frames.append(old_frame)
            old_pli += int(pli)
            _, frame = measured.add(packet)
            if frame:
                emitted.append(frame)
        self.assertGreater(old_pli, 0)
        self.assertFalse(any(len(f.data) == 300 * 1200 for f in old_frames))
        self.assertEqual(len(emitted), 1)
        self.assertEqual(len(emitted[0].data), 300 * 1200)
        self.assertEqual(measured.report()["pliRequests"], 0)
        self.assertEqual(measured.report()["overLegacyCapacityFrames"], 1)
        self.assertEqual(measured.report()["prefetchFrames"], 0)

    def test_adapter_refuses_unknown_runtime_and_used_buffer(self):
        from aiortc.jitterbuffer import JitterBuffer

        receiver = SimpleNamespace(_RTCRtpReceiver__jitter_buffer=JitterBuffer(128, is_video=True))
        with patch("motor_worker.receiver.version", return_value="1.16.0"):
            with self.assertRaisesRegex(ProtocolError, "unsupported_h264_receiver_version"):
                configure_h264_receiver(receiver)
        receiver._RTCRtpReceiver__jitter_buffer._origin = 1
        with self.assertRaisesRegex(ProtocolError, "unsupported_h264_receiver_state"):
            configure_h264_receiver(receiver)

    def test_missing_packet_does_not_hold_new_frames_until_capacity_overflows(self):
        from aiortc.jitterbuffer import JitterBuffer
        from aiortc.rtp import RtpPacket

        now = [0.0]
        receiver = SimpleNamespace(_RTCRtpReceiver__jitter_buffer=JitterBuffer(128, is_video=True))
        measured = configure_h264_receiver(receiver, clock=lambda: now[0])

        def add(sequence, timestamp):
            packet = RtpPacket(sequence_number=sequence, timestamp=timestamp)
            packet._data = bytes([sequence])
            return measured.add(packet)

        add(0, 1000)
        now[0] = 0.1
        self.assertEqual(add(2, 2000), (False, None))  # Lost sequence1 blocks origin.
        now[0] = 0.8
        self.assertEqual(add(3, 3000), (True, None))
        now[0] = 0.9
        _, frame = add(4, 4000)
        self.assertEqual((frame.timestamp, frame.data), (3000, b"\x03"))
        self.assertEqual(add(1, 1000), (False, None))  # Late old data is not replayed.
        now[0] = 1.8
        self.assertEqual(add(1, 1000), (False, None))  # Nor can an old packet reset origin after the deadline.
        _, next_frame = add(5, 5000)
        self.assertEqual((next_frame.timestamp, next_frame.data), (4000, b"\x04"))
        self.assertEqual(measured.report()["stallRecoveries"], 1)

    def test_slow_but_complete_large_idr_is_emitted_without_false_recovery(self):
        from aiortc.jitterbuffer import JitterBuffer
        from aiortc.rtp import RtpPacket

        now = [0.0]
        receiver = SimpleNamespace(_RTCRtpReceiver__jitter_buffer=JitterBuffer(128, is_video=True))
        measured = configure_h264_receiver(receiver, clock=lambda: now[0])
        emitted = []
        for index in range(301):
            now[0] = index / 250
            packet = RtpPacket(sequence_number=index, timestamp=1000 if index < 300 else 2000)
            packet._data = b"x" * 1200
            pli, frame = measured.add(packet)
            self.assertFalse(pli)
            if frame:
                emitted.append(frame)
        self.assertEqual(len(emitted[0].data), 300 * 1200)
        self.assertEqual(measured.report()["stallRecoveries"], 0)
