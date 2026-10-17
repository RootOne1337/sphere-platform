package com.sphereplatform.agent.streaming

import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class GpuFramePumpTest {
    private val throttle = mockk<FrameThrottle>().also {
        every { it.shouldRenderFrame(any()) } returns true
    }
    private val quality = StreamQualityMonitor()
    private val pump = GpuFramePump(throttle, quality)

    @Test fun `producer timestamps count real pictures not repeated callbacks`() {
        var draws = 0
        for (time in listOf(0L, 1L, 1L, 0L, 2L)) pump.frame(time) { draws++ }
        assertEquals(2, draws)
        assertEquals(2L, quality.getStats().captureFramesTotal)
        assertEquals(2L, quality.getStats().renderedFramesTotal)
    }

    @Test fun `30 moving producer pictures can pass without periodic synthetic copies`() {
        var draws = 0
        repeat(30) { pump.frame(1_000_000_000L + it * 33_333_333L) { draws++ } }
        assertEquals(30, draws)
        assertEquals(30L, quality.getStats().renderedFramesTotal)
        assertEquals(0L, quality.getStats().captureThrottleDropsTotal)
        // This tests the raw gate, not actual EGL, MediaCodec or device FPS.
    }

    @Test fun `budget drops before GL submission without encoded losses`() {
        every { throttle.shouldRenderFrame(any()) } returns false
        pump.frame(1L) { fail("raw skip must not submit to codec") }
        assertEquals(1L, quality.getStats().captureFramesTotal)
        assertEquals(1L, quality.getStats().captureThrottleDropsTotal)
        assertEquals(0L, quality.getStats().renderedFramesTotal)
        assertEquals(0L, quality.getStats().frameThrottleDropsTotal)
    }

    @Test fun `failed GL submission never becomes a successfully rendered picture`() {
        val error = IllegalStateException("swap failed")
        try { pump.frame(1L) { throw error }; fail("submission failure must propagate") }
        catch (observed: IllegalStateException) { assertSame(error, observed) }
        assertEquals(1L, quality.getStats().renderFailuresTotal)
        assertEquals(0L, quality.getStats().renderedFramesTotal)
    }

    @Test fun `close fences callbacks and does not block an in-flight native draw`() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val executor = Executors.newSingleThreadExecutor()
        val draw = executor.submit { pump.frame(1L) { entered.countDown(); check(release.await(3, TimeUnit.SECONDS)) } }
        try {
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            pump.close()
            quality.reset()
            pump.frame(2L) { fail("closed pump rendered") }
        } finally { release.countDown(); draw.get(2, TimeUnit.SECONDS); executor.shutdownNow() }
        assertEquals(0L, quality.getStats().captureFramesTotal)
        assertEquals(0L, quality.getStats().renderedFramesTotal)
    }
}
