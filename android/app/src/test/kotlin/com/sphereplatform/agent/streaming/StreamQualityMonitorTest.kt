package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
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
        assertEquals(0, stats.totalFrames)
        assertEquals(0L, stats.totalBytesSent)
        assertEquals(0f, stats.avgFrameSizeKb, 0.001f)
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
        assertEquals(1, stats.totalFrames)
        assertEquals(1024L, stats.totalBytesSent)
    }

    @Test
    fun `запись keyframe — keyFrameRatio корректен`() {
        monitor.recordFrame(5000, true)
        monitor.recordFrame(1000, false)
        monitor.recordFrame(1000, false)
        monitor.recordFrame(1000, false)
        val stats = monitor.getStats()
        assertEquals(4, stats.totalFrames)
        // 1 keyframe / 4 total = 0.25
        assertEquals(0.25f, stats.keyFrameRatio, 0.001f)
    }

    @Test
    fun `totalBytesSent — суммирует все фреймы`() {
        monitor.recordFrame(1000, false)
        monitor.recordFrame(2000, true)
        monitor.recordFrame(3000, false)
        assertEquals(6000L, monitor.getStats().totalBytesSent)
    }

    @Test
    fun `avgFrameSizeKb — среднее в килобайтах`() {
        // 3 фрейма по 1024 байт = 1024 * 3 / 3 / 1024 = 1.0 KB
        monitor.recordFrame(1024, false)
        monitor.recordFrame(1024, false)
        monitor.recordFrame(1024, true)
        assertEquals(1.0f, monitor.getStats().avgFrameSizeKb, 0.01f)
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

    // ── Reset ────────────────────────────────────────────────────────────────

    @Test
    fun `reset сбрасывает все счётчики`() {
        monitor.recordFrame(1000, true)
        monitor.recordFrame(2000, false)
        monitor.recordFrame(3000, false)

        monitor.reset()

        val stats = monitor.getStats()
        assertEquals(0, stats.currentFps)
        assertEquals(0, stats.totalFrames)
        assertEquals(0L, stats.totalBytesSent)
        assertEquals(0f, stats.keyFrameRatio, 0.001f)
        assertEquals(0f, stats.avgFrameSizeKb, 0.001f)
    }

    @Test
    fun `после reset можно продолжить записывать фреймы`() {
        monitor.recordFrame(1000, true)
        monitor.reset()
        monitor.recordFrame(2000, false)

        val stats = monitor.getStats()
        assertEquals(1, stats.totalFrames)
        assertEquals(2000L, stats.totalBytesSent)
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
        assertEquals(threadCount * framesPerThread, stats.totalFrames)
    }
}
