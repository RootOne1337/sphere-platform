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

    /** Map one whole live gesture; inactive/resized capture returns null. */
    fun mapStreamPoints(points: List<StreamPoint>): List<StreamPoint>? = null

    /** Valid only while the same capture and physical display remain current. */
    fun getInputSession(): CaptureInputSession? = null

    /** One synchronous invalidation listener; must not perform IO or wait for cleanup. */
    fun setInputInvalidationListener(listener: (() -> Unit)?) {}

    /** One read-only subscriber to the existing encoder; never creates a capture or codec. */
    fun attachEncodedViewer(owner: Any, consume: (EncodedCaptureFrame) -> Unit): CaptureInputSession? = null

    /** Exact-owner removal: a late peer close cannot detach its replacement. */
    fun detachEncodedViewer(owner: Any) {}

    /** Lock-free fence for encoder/native callbacks, including same-size capture restarts. */
    fun isEncodedViewerCurrent(owner: Any, capture: CaptureInputSession): Boolean = false
}
