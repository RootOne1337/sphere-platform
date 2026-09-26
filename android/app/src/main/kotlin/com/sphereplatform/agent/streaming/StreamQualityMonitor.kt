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
    private val captureTimestamps = ArrayDeque<Long>()
    private val renderTimestamps = ArrayDeque<Long>()
    private var encodedBytesTotal = 0L
    private var frameCount = 0L
    private var keyFrameCount = 0L
    private var captureFramesTotal = 0L
    private var renderedFramesTotal = 0L
    private var captureReadFailuresTotal = 0L
    private var renderFailuresTotal = 0L
    private var encoderErrorsTotal = 0L
    private var frameThrottleDropsTotal = 0L
    private var webSocketQueueAttemptsTotal = 0L
    private var webSocketQueueAcceptedTotal = 0L
    private var webSocketQueueRejectedTotal = 0L
    private var webSocketQueueAcceptedBytesTotal = 0L

    @Synchronized
    fun recordFrame(sizeBytes: Int, isKeyFrame: Boolean, isCodecConfig: Boolean = false) {
        // SPS/PPS describe the decoder configuration, not a displayed media frame.
        if (isCodecConfig) return
        val now = SystemClock.elapsedRealtime()
        frameTimestamps.addLast(now)
        evictExpiredFrames(now)

        encodedBytesTotal += sizeBytes.coerceAtLeast(0)
        frameCount++
        if (isKeyFrame) keyFrameCount++
    }

    @Synchronized
    fun recordCapturedFrame() {
        val now = SystemClock.elapsedRealtime()
        captureTimestamps.addLast(now)
        evictExpired(captureTimestamps, now)
        captureFramesTotal++
    }

    @Synchronized
    fun recordCaptureReadFailure() {
        captureReadFailuresTotal++
    }

    @Synchronized
    fun recordRenderedFrame() {
        val now = SystemClock.elapsedRealtime()
        renderTimestamps.addLast(now)
        evictExpired(renderTimestamps, now)
        renderedFramesTotal++
    }

    @Synchronized
    fun recordRenderFailure() {
        renderFailuresTotal++
    }

    @Synchronized
    fun recordEncoderError() {
        encoderErrorsTotal++
    }

    @Synchronized
    fun recordFrameThrottleDrop() {
        frameThrottleDropsTotal++
    }

    /** Records whether OkHttp accepted an encoded frame into its local WS queue. */
    @Synchronized
    fun recordWebSocketQueueResult(sizeBytes: Int, accepted: Boolean) {
        webSocketQueueAttemptsTotal++
        if (accepted) {
            webSocketQueueAcceptedTotal++
            webSocketQueueAcceptedBytesTotal += sizeBytes.coerceAtLeast(0)
        } else {
            webSocketQueueRejectedTotal++
        }
    }

    @Synchronized
    fun getStats(): StreamStats {
        // Prune during reads too: after an encoder stalls, no new frame arrives to
        // evict the old timestamps, so otherwise FPS would remain falsely non-zero.
        evictExpiredFrames(SystemClock.elapsedRealtime())
        val now = SystemClock.elapsedRealtime()
        evictExpired(captureTimestamps, now)
        evictExpired(renderTimestamps, now)
        return StreamStats(
            currentFps = frameTimestamps.size,
            currentCaptureFps = captureTimestamps.size,
            currentRenderFps = renderTimestamps.size,
            totalFrames = frameCount,
            totalEncodedBytes = encodedBytesTotal,
            keyFrameRatio = keyFrameCount.toFloat() / frameCount.coerceAtLeast(1L),
            avgEncodedFrameSizeKb = if (frameCount > 0) encodedBytesTotal / frameCount / 1024f else 0f,
            captureFramesTotal = captureFramesTotal,
            renderedFramesTotal = renderedFramesTotal,
            captureReadFailuresTotal = captureReadFailuresTotal,
            renderFailuresTotal = renderFailuresTotal,
            encoderErrorsTotal = encoderErrorsTotal,
            frameThrottleDropsTotal = frameThrottleDropsTotal,
            webSocketQueueAttemptsTotal = webSocketQueueAttemptsTotal,
            webSocketQueueAcceptedTotal = webSocketQueueAcceptedTotal,
            webSocketQueueRejectedTotal = webSocketQueueRejectedTotal,
            webSocketQueueAcceptedBytesTotal = webSocketQueueAcceptedBytesTotal,
        )
    }

    private fun evictExpiredFrames(nowElapsedMs: Long) {
        evictExpired(frameTimestamps, nowElapsedMs)
    }

    private fun evictExpired(timestamps: ArrayDeque<Long>, nowElapsedMs: Long) {
        while (timestamps.isNotEmpty() && nowElapsedMs - timestamps.peekFirst()!! > 1_000) {
            timestamps.removeFirst()
        }
    }

    /**
     * FIX F3: Сброс счётчиков при остановке стрима.
     * Без этого при start→stop→start метрики новой сессии включали данные прошлой.
     * Вызывается из StreamingManagerImpl.stopInternal().
     */
    @Synchronized
    fun reset() {
        frameTimestamps.clear()
        captureTimestamps.clear()
        renderTimestamps.clear()
        encodedBytesTotal = 0L
        frameCount = 0
        keyFrameCount = 0
        captureFramesTotal = 0L
        renderedFramesTotal = 0L
        captureReadFailuresTotal = 0L
        renderFailuresTotal = 0L
        encoderErrorsTotal = 0L
        frameThrottleDropsTotal = 0L
        webSocketQueueAttemptsTotal = 0L
        webSocketQueueAcceptedTotal = 0L
        webSocketQueueRejectedTotal = 0L
        webSocketQueueAcceptedBytesTotal = 0L
    }

    data class StreamStats(
        val currentFps: Int,
        val currentCaptureFps: Int = 0,
        val currentRenderFps: Int = 0,
        val totalFrames: Long,
        val totalEncodedBytes: Long,
        val keyFrameRatio: Float,
        val avgEncodedFrameSizeKb: Float,
        val captureFramesTotal: Long = 0,
        val renderedFramesTotal: Long = 0,
        val captureReadFailuresTotal: Long = 0,
        val renderFailuresTotal: Long = 0,
        val encoderErrorsTotal: Long = 0,
        val frameThrottleDropsTotal: Long = 0,
        val webSocketQueueAttemptsTotal: Long,
        val webSocketQueueAcceptedTotal: Long,
        val webSocketQueueRejectedTotal: Long,
        val webSocketQueueAcceptedBytesTotal: Long,
    )
}
