package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class DirectProbeProtocolTest {
    private val sid = "a".repeat(32)
    private val sdp = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:sha-256 " +
        List(32) { "AB" }.joinToString(":") + "\r\n"
    @Test fun onlyBoundedDataChannelSdpIsAccepted() {
        assertTrue(DirectProbeProtocol.validSdp(sdp))
        for (bad in listOf("", sdp.repeat(500), sdp + "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            sdp.replace("sha-256", "sha-1"), sdp + "a=candidate:x\r\n".repeat(65)))
            assertFalse(DirectProbeProtocol.validSdp(bad))
    }
    @Test fun echoRejectsWrongSessionReplayCommandsAndUnboundedInput() {
        assertEquals("SP1 $sid 1", DirectProbeProtocol.echo("SP1 $sid 1", sid, 1))
        for (bad in listOf("SP1 $sid 0", "SP1 $sid 2", "SP1 ${"b".repeat(32)} 1",
            "{\"type\":\"tap\",\"x\":10}", "x".repeat(100)))
            assertNull(DirectProbeProtocol.echo(bad, sid, 1))
        assertNull(DirectProbeProtocol.echo("SP1 $sid 65", sid, 65))
        assertFalse(DirectProbeProtocol.validSession("../../$sid"))
    }
}
