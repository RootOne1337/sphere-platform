import importlib.util
import unittest
from unittest.mock import AsyncMock, Mock, patch

from motor_worker.protocol import ProtocolError
from motor_worker.sctp_diagnostics import observe_sctp


@unittest.skipUnless(importlib.util.find_spec("aiortc"), "isolated motor runtime required")
class SctpDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiortc import RTCPeerConnection

        self.peer = RTCPeerConnection()
        self.peer.createDataChannel("fixture")
        self.transport = self.peer.sctp
        self.send = AsyncMock(return_value="sent")
        self.receive = AsyncMock(return_value="received")
        self.expired = Mock(return_value="expired")
        self.transport._send_chunk = self.send
        self.transport._receive_chunk = self.receive
        self.transport._t3_expired = self.expired

    async def asyncTearDown(self):
        await self.peer.close()

    def data(self, tsn=10, sent_count=1):
        from aiortc.rtcsctptransport import DataChunk

        chunk = DataChunk()
        chunk.tsn, chunk.stream_id, chunk._sent_count = tsn, 3, sent_count
        chunk.user_data = b"private-payload-do-not-report"
        return chunk

    async def test_calls_forward_exactly_and_timers_remain_unchanged(self):
        before = self.transport._rto
        observed = observe_sctp(self.transport)
        chunk = self.data()
        self.assertEqual(await self.transport._send_chunk(chunk), "sent")
        self.assertEqual(await self.transport._receive_chunk(chunk), "received")
        self.assertEqual(self.transport._t3_expired(), "expired")
        self.send.assert_awaited_once_with(chunk)
        self.receive.assert_awaited_once_with(chunk)
        self.expired.assert_called_once_with()
        self.assertEqual(self.transport._rto, before)
        self.assertEqual(observed.report()["t3Expiries"], 1)
        self.assertNotIn("private-payload", str(observed.report()))

    async def test_retransmission_duplicates_and_storage_are_bounded(self):
        observed = observe_sctp(self.transport)
        for tsn in range(2050):
            await self.transport._receive_chunk(self.data(tsn))
        await self.transport._receive_chunk(self.data(2049))
        await self.transport._receive_chunk(self.data(0))  # Outside duplicate window.
        await self.transport._send_chunk(self.data(sent_count=2))
        for _ in range(100):
            self.transport._t3_expired()
        report = observed.report()
        self.assertEqual(report["dataChunksRetransmitted"], 1)
        self.assertEqual(report["duplicatePeerDataChunks"], 1)
        self.assertEqual(len(observed.seen), 2048)
        self.assertEqual(len(report["eventTail"]), 64)
        self.assertNotIn("tsn", str(report).lower())

    async def test_original_exception_propagates_without_retry(self):
        self.send.side_effect = ConnectionError("fixture")
        observed = observe_sctp(self.transport)
        chunk = self.data()
        with self.assertRaises(ConnectionError):
            await self.transport._send_chunk(chunk)
        self.send.assert_awaited_once_with(chunk)
        self.assertEqual(observed.report()["dataChunksSent"], 1)

    async def test_unsupported_version_and_double_wrapping_refuse(self):
        with patch("motor_worker.sctp_diagnostics.version", return_value="future"):
            with self.assertRaisesRegex(ProtocolError, "unsupported_sctp_diagnostics_version"):
                observe_sctp(self.transport)
        observe_sctp(self.transport)
        with self.assertRaisesRegex(ProtocolError, "unsupported_sctp_diagnostics_state"):
            observe_sctp(self.transport)
