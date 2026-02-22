package com.sphereplatform.agent.ws

import timber.log.Timber
import javax.inject.Inject

/**
 * No-op [SphereWebSocketClientContract] placeholder.
 * Replaced when TZ-07 SPLIT-2 lands and wires the real OkHttp WebSocket client.
 */
class SphereWebSocketClientStub @Inject constructor() : SphereWebSocketClientContract {
    override fun sendBinary(data: ByteArray): Boolean {
        Timber.d("SphereWebSocketClientStub.sendBinary(${data.size} bytes) — TZ-07 not yet implemented")
        return false
    }
    override val isConnected: Boolean = false
}
