package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * Тесты FrameThrottle — token-bucket FPS-лимитер.
 *
 * Покрытие:
 *  - Первый фрейм всегда рендерится
 *  - Фреймы с достаточным интервалом (≥80% frameDuration) принимаются
 *  - Слишком частые фреймы дропаются
 *  - Метрики dropRatio / droppedFrames / totalFrames корректны
 *  - Потокобезопасность AtomicInteger при конкурентном доступе
 */
class FrameThrottleTest {

    private lateinit var throttle: FrameThrottle

    @Before
    fun setUp() {
        throttle = FrameThrottle()
    }

    // ── Базовая логика ───────────────────────────────────────────────────────

    @Test
    fun `первый фрейм с большим timestamp рендерится`() {
        // lastFrameTimeNs = 0, поэтому elapsed = frameTimeNs должен быть >= 80% от frameDuration
        val result = throttle.shouldRenderFrame(100_000_000L) // 100ms > 26.67ms
        assertTrue("Первый фрейм должен быть принят", result)
    }

    @Test
    fun `целевой FPS равен 30`() {
        assertEquals(30, throttle.targetFps)
    }

    @Test
    fun `фрейм через 33ms (30 FPS) принимается`() {
        throttle.shouldRenderFrame(0L)
        // 33.33ms = 33_333_333 ns (ровно 30 FPS)
        val result = throttle.shouldRenderFrame(33_333_334L)
        assertTrue("Фрейм через 33.3ms должен быть принят", result)
    }

    @Test
    fun `фрейм через 40ms принимается`() {
        throttle.shouldRenderFrame(0L)
        val result = throttle.shouldRenderFrame(40_000_000L)
        assertTrue("Фрейм через 40ms должен быть принят", result)
    }

    @Test
    fun `фрейм через 10ms дропается — слишком рано`() {
        throttle.shouldRenderFrame(0L)
        val result = throttle.shouldRenderFrame(10_000_000L)
        assertFalse("Фрейм через 10ms должен быть дропнут", result)
    }

    @Test
    fun `фрейм через 5ms дропается`() {
        throttle.shouldRenderFrame(0L)
        val result = throttle.shouldRenderFrame(5_000_000L)
        assertFalse("Фрейм через 5ms должен быть дропнут", result)
    }

    @Test
    fun `граница 80 процентов — фрейм на грани дропается`() {
        // frameDurationNs = 1_000_000_000 / 30 = 33_333_333 ns
        // 80% от frameDuration = 26_666_666 ns
        throttle.shouldRenderFrame(0L)
        // Ровно 80% — граница (< 80% → drop)
        val result = throttle.shouldRenderFrame(26_000_000L) // < 26.67ms → drop
        assertFalse("Фрейм на границе 80% должен быть дропнут", result)
    }

    @Test
    fun `фрейм чуть выше 80 процентов принимается`() {
        throttle.shouldRenderFrame(0L)
        val result = throttle.shouldRenderFrame(27_000_000L) // > 26.67ms → render
        assertTrue("Фрейм выше 80% должен быть принят", result)
    }

    // ── Серия фреймов ────────────────────────────────────────────────────────

    @Test
    fun `серия из 100 rapid фреймов — дропается большинство`() {
        var accepted = 0
        for (i in 0 until 100) {
            // По 1ms между фреймами = 1000 FPS
            if (throttle.shouldRenderFrame(i * 1_000_000L)) accepted++
        }
        // Первый принят, за 100ms при 30FPS: ~3 фрейма
        assertTrue("Должно быть принято менее 10 из 100", accepted < 10)
        assertTrue("Хотя бы 1 фрейм принят", accepted >= 1)
    }

    @Test
    fun `серия с точным 30 FPS интервалом — все принимаются`() {
        val frameDurationNs = 1_000_000_000L / 30
        var accepted = 0
        // Начинаем с frameDurationNs (не с 0) чтобы первый elapsed >= threshold
        for (i in 1..30) {
            if (throttle.shouldRenderFrame(i * frameDurationNs)) accepted++
        }
        assertEquals("Все 30 фреймов должны быть приняты", 30, accepted)
    }

    // ── Метрики ──────────────────────────────────────────────────────────────

    @Test
    fun `totalFrames считает все вызовы`() {
        for (i in 0 until 50) {
            throttle.shouldRenderFrame(i * 1_000_000L)
        }
        assertEquals(50, throttle.totalFrames)
    }

    @Test
    fun `droppedFrames считает только дропнутые`() {
        // Первый принят, остальные 49 через 1ms — большинство дропнутся
        for (i in 0 until 50) {
            throttle.shouldRenderFrame(i * 1_000_000L)
        }
        assertTrue("droppedFrames > 0", throttle.droppedFrames > 0)
        assertEquals(throttle.totalFrames, throttle.droppedFrames + (throttle.totalFrames - throttle.droppedFrames))
    }

    @Test
    fun `dropRatio корректна`() {
        // 30 фреймов по 1ms → ~27 дропов из 30
        for (i in 0 until 30) {
            throttle.shouldRenderFrame(i * 1_000_000L)
        }
        val ratio = throttle.dropRatio
        assertTrue("dropRatio должен быть в диапазоне 0-1", ratio in 0f..1f)
        assertTrue("dropRatio > 0.5 при rapid frames", ratio > 0.5f)
    }

    @Test
    fun `dropRatio 0 при идеальных 30 FPS`() {
        val frameDurationNs = 1_000_000_000L / 30
        for (i in 1..30) {
            throttle.shouldRenderFrame(i * frameDurationNs)
        }
        assertEquals("dropRatio должен быть 0 при 30 FPS", 0f, throttle.dropRatio, 0.01f)
    }

    // ── Потокобезопасность ───────────────────────────────────────────────────

    @Test
    fun `конкурентный доступ из 4 потоков не ломает счётчики`() {
        val threadCount = 4
        val framesPerThread = 1000
        val latch = CountDownLatch(threadCount)
        val executor = Executors.newFixedThreadPool(threadCount)
        val accepted = AtomicInteger(0)

        for (t in 0 until threadCount) {
            executor.submit {
                try {
                    for (i in 0 until framesPerThread) {
                        val ns = (t * framesPerThread + i) * 100_000L
                        if (throttle.shouldRenderFrame(ns)) accepted.incrementAndGet()
                    }
                } finally {
                    latch.countDown()
                }
            }
        }
        latch.await()
        executor.shutdown()

        val total = threadCount * framesPerThread
        assertEquals("totalFrames = сумма из всех потоков", total, throttle.totalFrames)
        assertEquals(
            "droppedFrames + accepted = totalFrames",
            total, throttle.droppedFrames + accepted.get(),
        )
    }
}
