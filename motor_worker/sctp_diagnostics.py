"""Bounded observation of aiortc1.15 SCTP, without changing its reliability/timers.

Standard getStats omits SCTP retransmission details. These per-instance wrappers
forward the exact original call; payloads, TSNs and peer addresses never enter
the report. A retry at this layer is SCTP delivery, not an application replay.
"""

import time
from collections import OrderedDict, deque
from importlib.metadata import version

from motor_worker.protocol import ProtocolError


def observe_sctp(transport, *, clock=time.perf_counter):
    if version("aiortc") != "1.15.0":
        raise ProtocolError("unsupported_sctp_diagnostics_version")
    from aiortc.rtcsctptransport import DataChunk, RTCSctpTransport

    if (
        type(transport) is not RTCSctpTransport
        or transport.state != "new"
        or getattr(transport, "_sphere_diagnostics", False)
        or any(not callable(getattr(transport, name, None))
               for name in ("_send_chunk", "_receive_chunk", "_t3_expired"))
    ):
        raise ProtocolError("unsupported_sctp_diagnostics_state")

    class Observation:
        def __init__(self):
            self.started = clock()
            self.sent = self.received = self.retransmitted = self.duplicates = self.expiries = 0
            self.seen = OrderedDict()
            self.events = deque(maxlen=64)

        def event(self, kind, stream=None):
            self.events.append({
                "kind": kind, "elapsedMs": round((clock() - self.started) * 1000, 3),
                "streamId": stream, "rtoMs": round(transport._rto * 1000, 3),
                "flightBytes": transport._flight_size,
            })

        def report(self):
            return {
                "evidence": "aiortc_1_15_observation_only_adapter",
                "dataChunksSent": self.sent, "dataChunksReceived": self.received,
                "dataChunksRetransmitted": self.retransmitted,
                "duplicatePeerDataChunks": self.duplicates, "t3Expiries": self.expiries,
                "rtoMs": round(transport._rto * 1000, 3),
                "smoothedRttMs": round(transport._srtt * 1000, 3)
                if transport._srtt is not None else None,
                "eventTail": list(self.events), "eventTailLimit": 64,
                "duplicateWindowChunks": 2048,
                "timersAndReliabilityChanged": False,
                "applicationCommandReplay": False,
            }

    observed = Observation()
    send, receive, expired = transport._send_chunk, transport._receive_chunk, transport._t3_expired

    async def measured_send(chunk):
        if isinstance(chunk, DataChunk):
            observed.sent += 1
            if chunk._sent_count > 1:
                observed.retransmitted += 1
                observed.event("local_retransmit", chunk.stream_id)
        return await send(chunk)

    async def measured_receive(chunk):
        if isinstance(chunk, DataChunk):
            observed.received += 1
            if chunk.tsn in observed.seen:
                observed.duplicates += 1
                observed.event("duplicate_peer_data", chunk.stream_id)
            observed.seen[chunk.tsn] = None
            observed.seen.move_to_end(chunk.tsn)
            if len(observed.seen) > 2048:
                observed.seen.popitem(last=False)
        return await receive(chunk)

    def measured_expired():
        observed.expiries += 1
        observed.event("t3_expired")
        return expired()

    transport._send_chunk, transport._receive_chunk, transport._t3_expired = (
        measured_send, measured_receive, measured_expired
    )
    transport._sphere_diagnostics = True
    return observed
