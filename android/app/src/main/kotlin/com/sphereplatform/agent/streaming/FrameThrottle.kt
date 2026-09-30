package com.sphereplatform.agent.streaming

import javax.inject.Inject
import javax.inject.Singleton

/**
 * Minimum-interval gate for raw ImageReader capture before CPU copy and
 * MediaCodec submission. Never apply this to an encoded H.264 reference chain.
 *
 * The manager serializes capture callbacks and supplies a monotonic timestamp.
 * Network/server queue backpressure is a separate stage.
 */
@Singleton
class FrameThrottle @Inject constructor() {

    val targetFps: Int = 30

    private val frameDurationNs = 1_000_000_000L / targetFps
    /**
     * PERF: Pre-computed минимальный интервал (80% от полного).
     * До: `frameDurationNs * 0.8` = Long→Double конвертация + Float multiply на каждый кадр (30 fps).
     * После: одно Long-сравнение на горячем пути raw capture.
     */
    private val minFrameIntervalNs = frameDurationNs * 4L / 5L  // 80% без Float
    @Volatile private var lastFrameTimeNs = 0L

    /**
     * FIX F2: Счётчики дропов обёрнуты в AtomicInteger — доступ из capture callback
     * thread (shouldRenderFrame) и heartbeat thread (dropRatio, droppedFrames, totalFrames).
     * Без синхронизации — data race на ARM/x86 (разный memory ordering).
     */
    private val _droppedFrames = java.util.concurrent.atomic.AtomicInteger(0)
    private val _totalFrames = java.util.concurrent.atomic.AtomicInteger(0)

    /**
     * Returns `true` if the frame should be rendered/encoded; `false` if it
     * should be skipped (too soon after the previous accepted frame).
     *
     * @param frameTimeNs monotonic capture-callback timestamp in nanoseconds.
     */
    fun shouldRenderFrame(frameTimeNs: Long): Boolean {
        _totalFrames.incrementAndGet()
        val elapsed = frameTimeNs - lastFrameTimeNs

        if (elapsed < minFrameIntervalNs) {
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
