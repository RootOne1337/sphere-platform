"""Guarded aiortc1.15 adapter for large, bounded H264 access units.

The stock128 RTP packet slots can discard an entire high-quality IDR before it
reaches the decoder. More packet slots do not add prefetch or a playout delay.
"""

import time
from importlib.metadata import version

from motor_worker.protocol import ProtocolError

H264_PACKET_CAPACITY = 2048


def configure_h264_receiver(receiver, *, clock=time.perf_counter, encoded_observer=None):
    if encoded_observer is not None and not callable(encoded_observer):
        raise ProtocolError("invalid_encoded_observer")
    if version("aiortc") != "1.15.0":
        raise ProtocolError("unsupported_h264_receiver_version")
    from aiortc.jitterbuffer import JitterBuffer

    old = getattr(receiver, "_RTCRtpReceiver__jitter_buffer", None)
    if (
        type(old) is not JitterBuffer
        or old.capacity != 128
        or old._origin is not None
        or not old._is_video
        or old._prefetch != 0
    ):
        raise ProtocolError("unsupported_h264_receiver_state")

    class MeasuredBuffer(JitterBuffer):
        def __init__(self):
            super().__init__(H264_PACKET_CAPACITY, prefetch=0, is_video=True)
            self.last_timestamp = None
            self.frame_packets = 0
            self.max_frame_packets = 0
            self.over_legacy_capacity_frames = 0
            self.pli_requests = 0
            self.emitted_frames = 0
            self.last_progress_at = None
            self.stall_recoveries = 0
            self.newest_timestamp = None

        def add(self, packet):
            now = clock()
            new_timestamp = self.newest_timestamp is None or (
                0 < (packet.timestamp - self.newest_timestamp) % (2**32) < 2**31
            )
            forward_sequence = self._origin is None or (
                (packet.sequence_number - self._origin) % (2**16) < 2**15
            )
            if new_timestamp:
                self.newest_timestamp = packet.timestamp
            if self.last_progress_at is None:
                self.last_progress_at = now
            if packet.timestamp != self.last_timestamp:
                self.last_timestamp = packet.timestamp
                self.frame_packets = 0
            self.frame_packets += 1
            self.max_frame_packets = max(self.max_frame_packets, self.frame_packets)
            if self.frame_packets == 129:
                self.over_legacy_capacity_frames += 1
            pli, frame = super().add(packet)
            if frame is not None:
                self.last_progress_at = now
            elif new_timestamp and forward_sequence and now - self.last_progress_at >= 0.75:
                # Large capacity protects fragmented IDRs, but a missing packet
                # must not pin newer frames until2048 slots fill. First let the
                # normal buffer complete a possibly slow, intact IDR. Only if
                # that failed, abandon the stalled window at a new timestamp,
                # request an IDR and retain its first packet. No playout queue.
                self.remove(self.capacity)
                self._origin = None
                _, frame = super().add(packet)
                pli = True
                self.last_progress_at = now
                self.stall_recoveries += 1
            self.pli_requests += int(pli)
            self.emitted_frames += int(frame is not None)
            if encoded_observer is not None and (frame is not None or pli):
                encoded_observer(frame.data if frame else None, frame.timestamp if frame else None, now, pli)
            return pli, frame

        def report(self):
            return {
                "packetCapacity": self.capacity,
                "prefetchFrames": 0,
                "maxConsecutiveTimestampPackets": self.max_frame_packets,
                "overLegacyCapacityFrames": self.over_legacy_capacity_frames,
                "pliRequests": self.pli_requests,
                "emittedFrames": self.emitted_frames,
                "stallRecoveries": self.stall_recoveries,
                "stallRecoveryAfterMs": 750,
                "evidence": "aiortc_1_15_h264_packet_buffer_adapter",
            }

    result = MeasuredBuffer()
    receiver._RTCRtpReceiver__jitter_buffer = result
    return result
