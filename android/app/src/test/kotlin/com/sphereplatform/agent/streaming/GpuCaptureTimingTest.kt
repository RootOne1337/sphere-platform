package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Test

class GpuCaptureTimingTest {
    private var now = 0L
    private val reports = mutableListOf<GpuCaptureTiming.Snapshot>()
    private val timing = GpuCaptureTiming({ now }, reports::add)

    @Test fun `raw skips have texture samples but no invented submission timings`() {
        timing.record(2_000_000, null, null)
        now = 5_000_000_000
        timing.record(4_000_000, 3_000_000, 300_000_000)
        val sample = reports.single()
        assertEquals(2, sample.texture.samples)
        assertEquals(3.0, sample.texture.meanMs, 0.001)
        assertEquals(1, sample.swap.samples)
        assertEquals(300.0, sample.swap.maxMs, 0.001)
    }
    @Test fun `stop flushes a short window once and next window is independent`() {
        timing.record(1, 2, 3); now = 100_000_000; timing.flush(); timing.flush()
        assertEquals(1, reports.size)
        assertEquals(100, reports.single().windowMs)
        now = 5_100_000_000
        timing.record(10, 20, 30)
        assertEquals(2, reports.size)
        assertEquals(30L, reports.last().swap.totalNs)
        assertEquals(1, reports.last().swap.samples)
    }
    @Test fun `failed stages and clock regressions cannot become negative latency`() {
        timing.record(10, -1, null); now = -100; timing.flush()
        assertEquals(0, reports.single().draw.samples)
        assertEquals(0L, reports.single().windowMs)
    }
    @Test fun `pathological timing cannot overflow aggregate accounting`() {
        timing.record(Long.MAX_VALUE, Long.MAX_VALUE, Long.MAX_VALUE); timing.flush()
        assertEquals(60_000_000_000L, reports.single().swap.maxNs)
        assertEquals(60_000.0, reports.single().swap.meanMs, 0.001)
    }
}
