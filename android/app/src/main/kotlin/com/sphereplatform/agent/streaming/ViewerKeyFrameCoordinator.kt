package com.sphereplatform.agent.streaming

/**
 * Keeps the first viewer key-frame request until screen capture and the encoder
 * are ready. The viewer can connect before Android finishes starting capture.
 */
internal class ViewerKeyFrameCoordinator {
    private var encoderReady = false
    private var requestPending = false

    @Synchronized
    fun request(requestKeyFrame: () -> Unit): Boolean {
        if (!encoderReady) {
            requestPending = true
            return false
        }
        requestKeyFrame()
        return true
    }

    @Synchronized
    fun markEncoderReady(requestKeyFrame: () -> Unit) {
        encoderReady = true
        if (!requestPending) return
        requestPending = false
        requestKeyFrame()
    }

    @Synchronized
    fun markEncoderStopped() {
        encoderReady = false
    }
}
