package com.sphereplatform.agent.streaming

/** Runs on the GL owner thread; timestamps identify real producer buffers. */
internal class GpuFramePump(
    private val throttle: FrameThrottle,
    private val quality: StreamQualityMonitor,
) {
    private var lastTimestamp = 0L
    private var closed = false
    private val lock = Any()

    fun frame(timestampNs: Long, render: () -> Unit) {
        frameAccepted(timestampNs) { render(); true }
    }

    /** A busy planar codec is a raw-input drop, never a rendered/encoded picture. */
    fun frameAccepted(timestampNs: Long, render: () -> Boolean) {
        synchronized(lock) {
            if (closed || timestampNs <= lastTimestamp) return
            lastTimestamp = timestampNs
            quality.recordCapturedFrame()
            // Skip raw pictures, never codec output. Repeated texture callbacks do
            // not manufacture frames or inflate the reported capture rate.
            if (!throttle.shouldRenderFrame(timestampNs)) {
                quality.recordCaptureThrottleDrop()
                return
            }
        }
        try {
            val accepted = render()
            synchronized(lock) { if (!closed) {
                if (accepted) quality.recordRenderedFrame() else quality.recordEncoderInputDrop()
            } }
        } catch (error: Exception) {
            synchronized(lock) { if (!closed) quality.recordRenderFailure() }
            throw error
        }
    }

    fun close() { synchronized(lock) { closed = true } }
}
