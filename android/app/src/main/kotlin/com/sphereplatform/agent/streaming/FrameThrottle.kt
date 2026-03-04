package com.sphereplatform.agent.streaming

import javax.inject.Inject
import javax.inject.Singleton

/**
 * Token-bucket style frame throttle to cap output FPS before frames enter
 * the WebSocket pipeline (L1 agent-side backpressure — MERGE-1 TZ-05 SPLIT-4).
 *
 * Used in [Choreographer.FrameCallback] to decide whether to render the current
 * frame.  Pass the VSYNC timestamp from [doFrame] directly.
 *
 * L2 server-side backpressure is handled by [VideoStreamQueue] (TZ-03 SPLIT-3).
 */
@Singleton
class FrameThrottle @Inject constructor() {

    val targetFps: Int = 30

    private val frameDurationNs = 1_000_000_000L / targetFps
    @Volatile private var lastFrameTimeNs = 0L

    /**
     * FIX F2: Счётчики дропов обёрнуты в AtomicInteger — доступ из MediaCodec callback
     * thread (shouldRenderFrame) и heartbeat thread (dropRatio, droppedFrames, totalFrames).
     * Без синхронизации — data race на ARM/x86 (разный memory ordering).
     */
    private val _droppedFrames = java.util.concurrent.atomic.AtomicInteger(0)
    private val _totalFrames = java.util.concurrent.atomic.AtomicInteger(0)

    /**
     * Returns `true` if the frame should be rendered/encoded; `false` if it
     * should be skipped (too soon after the previous accepted frame).
     *
     * @param frameTimeNs VSYNC timestamp in nanoseconds (from Choreographer).
     */
    fun shouldRenderFrame(frameTimeNs: Long): Boolean {
        _totalFrames.incrementAndGet()
        val elapsed = frameTimeNs - lastFrameTimeNs

        if (elapsed < frameDurationNs * 0.8) {
            _droppedFrames.incrementAndGet()
            return false
        }

        lastFrameTimeNs = frameTimeNs
        return true
    }

    /** Ratio of skipped frames to total frames observed (0.0–1.0). */
    val dropRatio: Float
        get() = _droppedFrames.get().toFloat() / _totalFrames.get().coerceAtLeast(1)

    val droppedFrames: Int get() = _droppedFrames.get()
    val totalFrames: Int get() = _totalFrames.get()
}
