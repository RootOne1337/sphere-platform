package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class AvcReceiveCapabilitiesTest {
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
