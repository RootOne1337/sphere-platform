package com.sphereplatform.agent.streaming

import android.os.SystemClock
import java.util.ArrayDeque
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Collects per-frame metrics with a 1-second sliding window for FPS calculation.
 *
 * Thread-safe via [synchronized] — called from the MediaCodec encoder callback
 * thread and read from the heartbeat coroutine.
 */
@Singleton
class StreamQualityMonitor @Inject constructor() {

    private val frameTimestamps = ArrayDeque<Long>()
    private var bytesSentTotal = 0L
    private var frameCount = 0
    private var keyFrameCount = 0

    @Synchronized
    fun recordFrame(sizeBytes: Int, isKeyFrame: Boolean) {
        val now = SystemClock.elapsedRealtime()
        frameTimestamps.addLast(now)

        // Evict frames outside the 1-second window
        while (frameTimestamps.isNotEmpty() && (now - frameTimestamps.peekFirst()!!) > 1_000) {
            frameTimestamps.removeFirst()
        }

        bytesSentTotal += sizeBytes
        frameCount++
        if (isKeyFrame) keyFrameCount++
    }

    @Synchronized
    fun getStats(): StreamStats = StreamStats(
        currentFps = frameTimestamps.size,
        totalFrames = frameCount,
        totalBytesSent = bytesSentTotal,
        keyFrameRatio = keyFrameCount.toFloat() / frameCount.coerceAtLeast(1),
        avgFrameSizeKb = if (frameCount > 0) bytesSentTotal / frameCount / 1024f else 0f,
    )

    /**
     * FIX F3: Сброс счётчиков при остановке стрима.
     * Без этого при start→stop→start метрики новой сессии включали данные прошлой.
     * Вызывается из StreamingManagerImpl.stopInternal().
     */
    @Synchronized
    fun reset() {
        frameTimestamps.clear()
        bytesSentTotal = 0L
        frameCount = 0
        keyFrameCount = 0
    }

    data class StreamStats(
        val currentFps: Int,
        val totalFrames: Int,
        val totalBytesSent: Long,
        val keyFrameRatio: Float,
        val avgFrameSizeKb: Float,
    )
}
