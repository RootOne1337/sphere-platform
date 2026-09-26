package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors

/**
 * Тесты StreamQualityMonitor — метрики стрима со скользящим окном 1 секунда.
 *
 * Используем Robolectric для эмуляции SystemClock.elapsedRealtime().
 */
@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, sdk = [33])
class StreamQualityMonitorTest {

    private lateinit var monitor: StreamQualityMonitor

    @Before
    fun setUp() {
        monitor = StreamQualityMonitor()
    }

    // ── Пустое состояние ─────────────────────────────────────────────────────

    @Test
    fun `пустой монитор — все метрики нулевые`() {
        val stats = monitor.getStats()
        assertEquals(0, stats.currentFps)
        assertEquals(0L, stats.totalFrames)
        assertEquals(0L, stats.totalEncodedBytes)
        assertEquals(0f, stats.avgEncodedFrameSizeKb, 0.001f)
        assertEquals(0L, stats.webSocketQueueAttemptsTotal)
    }

    @Test
    fun `keyFrameRatio при 0 фреймов = 0`() {
        val stats = monitor.getStats()
        assertEquals(0f, stats.keyFrameRatio, 0.001f)
    }

    // ── Запись фреймов ───────────────────────────────────────────────────────

    @Test
    fun `запись одного фрейма — totalFrames = 1`() {
        monitor.recordFrame(1024, false)
        val stats = monitor.getStats()
        assertEquals(1L, stats.totalFrames)
        assertEquals(1024L, stats.totalEncodedBytes)
    }

    @Test
    fun `запись keyframe — keyFrameRatio корректен`() {
        monitor.recordFrame(5000, true)
        monitor.recordFrame(1000, false)
        monitor.recordFrame(1000, false)
        monitor.recordFrame(1000, false)
        val stats = monitor.getStats()
        assertEquals(4L, stats.totalFrames)
        // 1 keyframe / 4 total = 0.25
        assertEquals(0.25f, stats.keyFrameRatio, 0.001f)
    }

    @Test
    fun `totalEncodedBytes — суммирует encoder outputs`() {
        monitor.recordFrame(1000, false)
        monitor.recordFrame(2000, true)
        monitor.recordFrame(3000, false)
        assertEquals(6000L, monitor.getStats().totalEncodedBytes)
    }

    @Test
    fun `avgEncodedFrameSizeKb — среднее в килобайтах`() {
        // 3 фрейма по 1024 байт = 1024 * 3 / 3 / 1024 = 1.0 KB
        monitor.recordFrame(1024, false)
        monitor.recordFrame(1024, false)
        monitor.recordFrame(1024, true)
        assertEquals(1.0f, monitor.getStats().avgEncodedFrameSizeKb, 0.01f)
    }

    @Test
    fun `socket queue counters distinguish accepted and rejected frames`() {
        monitor.recordWebSocketQueueResult(1024, true)
        monitor.recordWebSocketQueueResult(2048, false)
        monitor.recordWebSocketQueueResult(512, true)

        val stats = monitor.getStats()
        assertEquals(3L, stats.webSocketQueueAttemptsTotal)
        assertEquals(2L, stats.webSocketQueueAcceptedTotal)
        assertEquals(1L, stats.webSocketQueueRejectedTotal)
        assertEquals(1536L, stats.webSocketQueueAcceptedBytesTotal)
    }

    @Test
    fun `capture render encode and queue stages keep independent counters`() {
        monitor.recordCapturedFrame()
        monitor.recordCapturedFrame()
        monitor.recordCaptureReadFailure()
        monitor.recordRenderedFrame()
        monitor.recordRenderFailure()
        monitor.recordEncoderError()
        monitor.recordFrame(900, isKeyFrame = false)
        monitor.recordFrameThrottleDrop()
        monitor.recordWebSocketQueueResult(900, accepted = true)

        val stats = monitor.getStats()
        assertEquals(2, stats.currentCaptureFps)
        assertEquals(1, stats.currentRenderFps)
        assertEquals(2L, stats.captureFramesTotal)
        assertEquals(1L, stats.renderedFramesTotal)
        assertEquals(1L, stats.captureReadFailuresTotal)
        assertEquals(1L, stats.renderFailuresTotal)
        assertEquals(1L, stats.encoderErrorsTotal)
        assertEquals(1L, stats.frameThrottleDropsTotal)
        assertEquals(1L, stats.totalFrames)
        assertEquals(1L, stats.webSocketQueueAcceptedTotal)
    }

    // ── currentFps (скользящее окно) ─────────────────────────────────────────
    // Примечание: используем recordFrame напрямую, SystemClock.elapsedRealtime()
    // внутри будет возвращать реальное время. Для unit-теста мы просто быстро
    // записываем фреймы (все в пределах 1с от начала теста).

    @Test
    fun `currentFps при быстрых фреймах — все в окне 1 секунды`() {
        // Записываем 30 фреймов за <100ms (все попадут в окно)
        repeat(30) { monitor.recordFrame(500, false) }
        val stats = monitor.getStats()
        assertEquals("currentFps = количество фреймов в окне 1с", 30, stats.currentFps)
    }

    @Test
    fun `currentFps falls to zero after encoder stops producing frames`() {
        monitor.recordFrame(500, false)
        ShadowSystemClock.advanceBy(Duration.ofMillis(1_100))

        assertEquals(0, monitor.getStats().currentFps)
    }

    @Test
    fun `codec config is excluded from encoded frame and fps counters`() {
        monitor.recordFrame(24, isKeyFrame = true, isCodecConfig = true)

        val stats = monitor.getStats()
        assertEquals(0L, stats.totalFrames)
        assertEquals(0L, stats.totalEncodedBytes)
        assertEquals(0, stats.currentFps)
        assertEquals(0f, stats.keyFrameRatio, 0.001f)
    }

    // ── Reset ────────────────────────────────────────────────────────────────

    @Test
    fun `reset сбрасывает все счётчики`() {
        monitor.recordFrame(1000, true)
        monitor.recordFrame(2000, false)
        monitor.recordFrame(3000, false)
        monitor.recordWebSocketQueueResult(100, true)
        monitor.recordWebSocketQueueResult(200, false)
        monitor.recordCapturedFrame()
        monitor.recordRenderedFrame()
        monitor.recordCaptureReadFailure()
        monitor.recordRenderFailure()
        monitor.recordEncoderError()
        monitor.recordFrameThrottleDrop()

        monitor.reset()

        val stats = monitor.getStats()
        assertEquals(0, stats.currentFps)
        assertEquals(0, stats.currentCaptureFps)
        assertEquals(0, stats.currentRenderFps)
        assertEquals(0L, stats.totalFrames)
        assertEquals(0L, stats.totalEncodedBytes)
        assertEquals(0L, stats.webSocketQueueAttemptsTotal)
        assertEquals(0L, stats.webSocketQueueAcceptedTotal)
        assertEquals(0L, stats.webSocketQueueRejectedTotal)
        assertEquals(0L, stats.webSocketQueueAcceptedBytesTotal)
        assertEquals(0L, stats.captureFramesTotal)
        assertEquals(0L, stats.renderedFramesTotal)
        assertEquals(0L, stats.captureReadFailuresTotal)
        assertEquals(0L, stats.renderFailuresTotal)
        assertEquals(0L, stats.encoderErrorsTotal)
        assertEquals(0L, stats.frameThrottleDropsTotal)
        assertEquals(0f, stats.keyFrameRatio, 0.001f)
        assertEquals(0f, stats.avgEncodedFrameSizeKb, 0.001f)
    }

    @Test
    fun `после reset можно продолжить записывать фреймы`() {
        monitor.recordFrame(1000, true)
        monitor.reset()
        monitor.recordFrame(2000, false)

        val stats = monitor.getStats()
        assertEquals(1L, stats.totalFrames)
        assertEquals(2000L, stats.totalEncodedBytes)
        assertEquals(0f, stats.keyFrameRatio, 0.001f) // 0 keyframes из 1
    }

    // ── Потокобезопасность ───────────────────────────────────────────────────

    @Test
    fun `конкурентные recordFrame и getStats не бросают исключений`() {
        val threadCount = 4
        val framesPerThread = 500
        val latch = CountDownLatch(threadCount + 1) // +1 для reader
        val executor = Executors.newFixedThreadPool(threadCount + 1)

        // Writer threads
        for (t in 0 until threadCount) {
            executor.submit {
                try {
                    for (i in 0 until framesPerThread) {
                        monitor.recordFrame(100 + i, i % 5 == 0)
                    }
                } finally {
                    latch.countDown()
                }
            }
        }
        // Reader thread
        executor.submit {
            try {
                for (i in 0 until framesPerThread) {
                    monitor.getStats()
                }
            } finally {
                latch.countDown()
            }
        }

        latch.await()
        executor.shutdown()

        val stats = monitor.getStats()
        assertEquals((threadCount * framesPerThread).toLong(), stats.totalFrames)
    }
}
