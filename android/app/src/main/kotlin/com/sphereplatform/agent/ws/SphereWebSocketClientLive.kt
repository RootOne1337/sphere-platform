package com.sphereplatform.agent.ws

import javax.inject.Inject
import javax.inject.Singleton

/**
 * Live adapter bridging [SphereWebSocketClient] (TZ-07 SPLIT-2) to the
 * [SphereWebSocketClientContract] interface consumed by StreamingManagerImpl (TZ-05).
 *
 * This replaces the no-op [SphereWebSocketClientStub] that was wired
 * during the split-branch development phase.
 */
@Singleton
class SphereWebSocketClientLive @Inject constructor(
    private val wsClient: SphereWebSocketClient,
) : SphereWebSocketClientContract {

    override fun sendBinary(data: ByteArray): Boolean = wsClient.sendBinary(data)

    override val isConnected: Boolean
        get() = wsClient.isConnected
}
