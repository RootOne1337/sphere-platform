package com.sphereplatform.agent.streaming

import android.content.Context
import android.view.Surface
import java.nio.ByteBuffer

/** Borrowed planes are valid only during submit; the encoder must own its cache. */
internal data class I420Planes(
    val width: Int, val height: Int,
    val y: ByteBuffer, val strideY: Int,
    val u: ByteBuffer, val strideU: Int,
    val v: ByteBuffer, val strideV: Int,
)

internal data class PlanarGpuRequest(
    val context: Context, val width: Int, val height: Int,
    val throttle: FrameThrottle, val quality: StreamQualityMonitor,
    val valid: () -> Boolean,
    val submit: (I420Planes, Long) -> Boolean,
    val refresh: () -> Unit, val refreshIntervalMs: Long,
    val failed: (Exception) -> Unit,
)

/** Optional source-set capability; ordinary APKs have no WebRTC dependency. */
internal interface PlanarGpuSource {
    fun start(): Surface
    fun close(afterRelease: () -> Unit = {})
    class InitializationFailed(cause: Throwable) : IllegalStateException("GPU planar initialization failed", cause)
    class InitializationTimedOut : IllegalStateException("GPU planar initialization deadline exceeded")
}
