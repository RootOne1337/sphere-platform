package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class AvcReceiveCapabilitiesTest {
    @Test fun `negotiated higher receive level and unrelated fmtp parameters admit the coded source`() {
        assertTrue(AvcReceiveCapabilities.acceptsParameters(mapOf("profile-level-id" to "42e029",
            "packetization-mode" to "1", "level-asymmetry-allowed" to "1", "x-google-start-bitrate" to "8000"), "42e020"))
        assertTrue(AvcReceiveCapabilities.acceptsParameters(mapOf("PROFILE-LEVEL-ID" to "42C020",
            "PACKETIZATION-MODE" to "1"), "42e020"))
    }
    @Test fun `encoder parameters cannot authorize a lower level different profile or single NAL mode`() {
        for (profile in listOf("42e01f", "640029", "not-a-profile")) {
            assertFalse(AvcReceiveCapabilities.acceptsParameters(mapOf("profile-level-id" to profile,
                "packetization-mode" to "1"), "42e020"))
        }
        assertFalse(AvcReceiveCapabilities.acceptsParameters(mapOf("profile-level-id" to "42e029",
            "packetization-mode" to "0"), "42e020"))
        assertFalse(AvcReceiveCapabilities.acceptsParameters(mapOf("packetization-mode" to "1"), "42e020"))
    }
    private fun sdp(profile: String = "42e02a", mode: Int = 1) = "a=rtpmap:96 H264/90000\r\na=fmtp:96 packetization-mode=$mode;profile-level-id=$profile;level-asymmetry-allowed=1\r\n"
    @Test fun `confirmed higher receive level admits a source ceiling but old level31 cannot`() {
        assertTrue(AvcReceiveCapabilities.accepts(sdp(), "42e029"))
        assertFalse(AvcReceiveCapabilities.accepts(sdp("42e01f"), "42e029"))
        assertTrue(AvcReceiveCapabilities.accepts(sdp("42e01f"), "42e01f"))
    }
    @Test fun `another codec payload or incompatible profile cannot authorize preencoded h264`() {
        assertFalse(AvcReceiveCapabilities.accepts(sdp().replace("H264", "VP9"), "42e029"))
        assertFalse(AvcReceiveCapabilities.accepts(sdp().replace("fmtp:96", "fmtp:97"), "42e029"))
        assertFalse(AvcReceiveCapabilities.accepts(sdp("64002a"), "42e029"))
        assertFalse(AvcReceiveCapabilities.accepts(sdp(mode = 0), "42e029"))
    }
    @Test fun `missing or malformed receive capability never authorizes a high level`() {
        for (value in listOf("", "42e0xx", "42e02aff", "<script>"))
            assertFalse(AvcReceiveCapabilities.accepts(sdp(value), "42e029"))
        assertFalse(AvcReceiveCapabilities.accepts(sdp(), "unknown"))
    }
}
