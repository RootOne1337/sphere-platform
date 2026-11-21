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

    @Volatile var targetFps: Int = 30
        private set
    /**
     * PERF: Pre-computed минимальный интервал (80% от полного).
     * До: `frameDurationNs * 0.8` = Long→Double конвертация + Float multiply на каждый кадр (30 fps).
     * После: одно Long-сравнение на горячем пути raw capture.
     */
    @Volatile private var minFrameIntervalNs = 1_000_000_000L / targetFps * 4L / 5L
    private var lastFrameTimeNs: Long? = null
    private var nextFrameTimeNs: Long? = null
    private var precise = false

    @Synchronized
    fun configure(fps: Int, newCapture: Boolean = false, precise: Boolean = true) {
        require(fps in 1..60)
        if (fps != targetFps || this.precise != precise) {
            nextFrameTimeNs = lastFrameTimeNs?.let { it + 1_000_000_000L / fps }
        }
        targetFps = fps
        this.precise = precise
        minFrameIntervalNs = 1_000_000_000L / fps * 4L / 5L
        if (newCapture) { lastFrameTimeNs = null; nextFrameTimeNs = null; _totalFrames.set(0); _droppedFrames.set(0) }
    }

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
    @Synchronized
    fun shouldRenderFrame(frameTimeNs: Long): Boolean {
        _totalFrames.incrementAndGet()
        val last = lastFrameTimeNs
        val elapsed = last?.let { frameTimeNs - it }

        val tooEarly = if (precise) nextFrameTimeNs?.let { frameTimeNs + 100_000L < it } == true
            else elapsed != null && elapsed < minFrameIntervalNs
        if (frameTimeNs < 0 || elapsed != null && elapsed < 0 || tooEarly) {
            _droppedFrames.incrementAndGet()
            return false
        }

        lastFrameTimeNs = frameTimeNs
        val interval = 1_000_000_000L / targetFps
        nextFrameTimeNs = ((nextFrameTimeNs ?: frameTimeNs) + interval).let {
            if (it <= frameTimeNs) frameTimeNs + interval else it
        }
        return true
    }

    /** Ratio of skipped frames to total frames observed (0.0–1.0). */
    val dropRatio: Float
        get() = _droppedFrames.get().toFloat() / _totalFrames.get().coerceAtLeast(1)

    val droppedFrames: Int get() = _droppedFrames.get()
    val totalFrames: Int get() = _totalFrames.get()
}
