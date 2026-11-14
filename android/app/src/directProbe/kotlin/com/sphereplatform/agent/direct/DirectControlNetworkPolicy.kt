package com.sphereplatform.agent.direct

import org.webrtc.PeerConnectionFactory

/** Control/media follows physical networks; an app VPN is never an ICE route. */
internal object DirectControlNetworkPolicy {
    fun factoryOptions() = PeerConnectionFactory.Options().apply {
        networkIgnoreMask = PeerConnectionFactory.Options.ADAPTER_TYPE_VPN or
            PeerConnectionFactory.Options.ADAPTER_TYPE_LOOPBACK
    }
}
