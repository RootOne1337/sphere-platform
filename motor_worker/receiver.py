"""Guarded aiortc1.15 adapter for large, bounded H264 access units.

The stock128 RTP packet slots can discard an entire high-quality IDR before it
reaches the decoder. More packet slots do not add prefetch or a playout delay.
"""

from importlib.metadata import version

from motor_worker.protocol import ProtocolError

H264_PACKET_CAPACITY = 2048


def configure_h264_receiver(receiver):
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

        def add(self, packet):
            if packet.timestamp != self.last_timestamp:
                self.last_timestamp = packet.timestamp
                self.frame_packets = 0
            self.frame_packets += 1
            self.max_frame_packets = max(self.max_frame_packets, self.frame_packets)
            if self.frame_packets == 129:
                self.over_legacy_capacity_frames += 1
            pli, frame = super().add(packet)
            self.pli_requests += int(pli)
            self.emitted_frames += int(frame is not None)
            return pli, frame

        def report(self):
            return {
                "packetCapacity": self.capacity,
                "prefetchFrames": 0,
                "maxConsecutiveTimestampPackets": self.max_frame_packets,
                "overLegacyCapacityFrames": self.over_legacy_capacity_frames,
                "pliRequests": self.pli_requests,
                "emittedFrames": self.emitted_frames,
                "evidence": "aiortc_1_15_h264_packet_buffer_adapter",
            }

    result = MeasuredBuffer()
    receiver._RTCRtpReceiver__jitter_buffer = result
    return result
