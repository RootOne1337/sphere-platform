package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class DirectVideoProtocolTest {
    private val app = "v=0\r\na=fingerprint:sha-256 " + List(32) { "AB" }.joinToString(":") +
        "\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
    private val video = "m=video 9 UDP/TLS/RTP/SAVPF 96\r\na=rtpmap:96 H264/90000\r\na=recvonly\r\n"
    @Test fun `RTP requires a distinct read only offer and matching send only answer`() {
        assertTrue(DirectVideoProtocol.validSdp(app + video, true))
        assertTrue(DirectVideoProtocol.validSdp(app + video.replace("recvonly", "sendonly"), false))
        assertFalse(DirectProbeProtocol.validSdp(app + video))
        assertFalse(DirectVideoProtocol.validSdp(app, true))
        assertFalse(DirectVideoProtocol.validSdp(app + video, false))
    }
    @Test fun `audio bidirectional video extra sections weak fingerprints and oversized descriptions are rejected`() {
        for (bad in listOf(app + video.replace("recvonly", "sendrecv"), app + video + "a=sendonly\r\n",
            app + video + "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n", app + video + video,
            app + video.replace("H264", "VP8"), (app + video).replace("sha-256", "sha-1"),
            app + video + "a=candidate:x\r\n".repeat(65), (app + video).repeat(1000)))
            assertFalse(DirectVideoProtocol.validSdp(bad, true))
    }
}
