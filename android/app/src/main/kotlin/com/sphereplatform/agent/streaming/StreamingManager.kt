package com.sphereplatform.agent.streaming

import android.media.projection.MediaProjection

/**
 * Orchestrates H.264 encoding pipeline.
 * Implemented in SPLIT-2 (MediaCodec). This interface decouples
 * ScreenCaptureService from the encoder so SPLIT-1 compiles independently.
 */
interface StreamingManager {
    /** Start capture+encoding pipeline using the granted [projection]. */
    fun start(projection: MediaProjection)

    /** Stop the pipeline and release all resources. */
    fun stop()

    /** Returns true when a streaming session is currently active. */
    fun isActive(): Boolean

    /** Returns stage-specific counters for the current stream, if available. */
    fun getQualityStats(): StreamQualityMonitor.StreamStats? = null

    /** Notify an active stream that a new viewer needs codec configuration and a keyframe. */
    fun onViewerConnected() {}
}
