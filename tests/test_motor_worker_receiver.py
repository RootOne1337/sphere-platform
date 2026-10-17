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
