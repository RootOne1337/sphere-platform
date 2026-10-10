package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class DirectProbeIceProfileTest {
    @Test fun noExternalServerByDefault() {
        assertEquals(DirectProbeIceProfile("host", null), DirectProbeIceProfile.fromUrl(""))
    }

    @Test fun documentedPublicServiceRequiresExactExplicitSelection() {
        assertEquals(DirectProbeIceProfile("public-stun", "stun:stun.cloudflare.com:3478"),
            DirectProbeIceProfile.fromUrl("stun:stun.cloudflare.com:3478"))
        for (url in listOf("stun:stun.cloudflare.com:19302", "stun:stun.cloudflare.com:3478?transport=udp",
            "stun:STUN.cloudflare.com:3478", "stun:stun.cloudflare.com.evil:3478")) {
            assertThrows(IllegalArgumentException::class.java) { DirectProbeIceProfile.fromUrl(url) }
        }
    }

    @Test fun singleCanonicalPrivateEndpointIsAdmitted() {
        for (url in listOf("stun:10.0.2.2:3478", "stun:172.16.1.1:1024",
            "stun:172.31.255.255:65535", "stun:192.168.1.2:19302")) {
            assertEquals(DirectProbeIceProfile("controlled-stun", url), DirectProbeIceProfile.fromUrl(url))
        }
    }

    @Test fun dnsPublicAddressesCredentialsOptionsAndNonCanonicalValuesAreRejected() {
        for (url in listOf("stun:example.com:3478", "stun:8.8.8.8:3478", "stun:127.0.0.1:3478",
            "stun:172.15.1.1:3478", "stun:172.32.1.1:3478", "stun:192.169.1.1:3478",
            "stun:10.0.2.256:3478", "stun:010.0.2.2:3478", "stun:10.0.2:3478", "stun:10.0.2.2.1:3478",
            "stun:10.0..2:3478", "stun:10.0.2.2:03478", "stun:10.0.2.2:65536", "stun:10.0.2.2:1023",
            "stun:10.0.2.2:9999999999999999999999", "STUN:10.0.2.2:3478", "stuns:10.0.2.2:3478",
            "turn:10.0.2.2:3478", "stun://10.0.2.2:3478", "stun:user@10.0.2.2:3478",
            "stun:10.0.2.2:3478?transport=udp", "stun:10.0.2.2:3478/path", "stun:10.0.2.2:3478#fragment",
            "stun:10.0.2.2:3478,stun:10.0.2.3:3478", " stun:10.0.2.2:3478", "stun:10.0.2.2:3478\n",
            "stun:[fd00::1]:3478")) {
            val error = assertThrows(IllegalArgumentException::class.java) { DirectProbeIceProfile.fromUrl(url) }
            assertEquals("invalid_controlled_stun", error.message)
        }
    }
}
