package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test
import org.webrtc.PeerConnectionFactory

class DirectControlNetworkPolicyTest {
    @Test fun `VPN and loopback are excluded without hiding physical network changes or disabling encryption`() {
        val options = DirectControlNetworkPolicy.factoryOptions()
        val mask = options.networkIgnoreMask
        assertNotEquals(0, mask and PeerConnectionFactory.Options.ADAPTER_TYPE_VPN)
        assertNotEquals(0, mask and PeerConnectionFactory.Options.ADAPTER_TYPE_LOOPBACK)
        for (physical in listOf(PeerConnectionFactory.Options.ADAPTER_TYPE_WIFI,
            PeerConnectionFactory.Options.ADAPTER_TYPE_ETHERNET, PeerConnectionFactory.Options.ADAPTER_TYPE_CELLULAR)) {
            assertEquals(0, mask and physical)
        }
        assertFalse(options.disableEncryption)
        assertFalse(options.disableNetworkMonitor)
    }
}
