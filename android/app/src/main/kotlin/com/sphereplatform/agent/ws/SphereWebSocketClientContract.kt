package com.sphereplatform.agent.ws

/**
 * Minimal contract for the WebSocket client used by [StreamingManagerImpl].
 *
 * Full implementation provided by TZ-07 SPLIT-2 (SphereWebSocketClient).
 * This interface exists so TZ-05 compiles independently on stage/5-streaming.
 */
interface SphereWebSocketClientContract {
    /**
     * Send a binary WebSocket frame.
     * @return `true` if the frame was enqueued successfully, `false` if the
     *         send queue is full or the connection is not established.
     */
    fun sendBinary(data: ByteArray): Boolean

    /** Whether the WebSocket connection is currently established. */
    val isConnected: Boolean
}
