package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Test

class StreamQualityPolicyTest {
    private val source = StreamQualityPolicy.Source(960, 540, 60f)
    @Test fun `native source retains sixty fps and a pixel-scaled detail ceiling`() {
        val plan = StreamQualityPolicy.plan(StreamQualitySettings(), source)
        assertEquals(60, plan.maxFps); assertEquals(12_441_600, plan.maxBitrate)
        assertEquals(2_000_000, plan.initialBitrate)
    }
    @Test fun `detail starts at the high ceiling instead of low bootstrap bitrate`() {
        val plan = StreamQualityPolicy.plan(StreamQualitySettings("detail"), source)
        assertEquals(plan.maxBitrate, plan.initialBitrate)
    }
    @Test fun `refresh cadence and actual codec limit both cap the requested rate`() {
        assertEquals(20, StreamQualityPolicy.plan(StreamQualitySettings(maxFps = 60), source.copy(refreshRate = 20f)).maxFps)
        assertEquals(30, StreamQualityPolicy.plan(StreamQualitySettings(), source.copy(codecMaxFps = 30)).maxFps)
        assertEquals(60, source.copy(refreshRate = 59.94f).maximumFps)
        assertEquals(60, source.copy(refreshRate = 120f).maximumFps)
    }
    @Test fun `missing or nonfinite display refresh cannot invent sixty fps`() {
        for (value in listOf(0f, -1f, Float.NaN, Float.POSITIVE_INFINITY))
            assertEquals(30, source.copy(refreshRate = value).maximumFps)
    }
    @Test fun `economy caps both cadence and bitrate while preserving picture dimensions`() {
        val plan = StreamQualityPolicy.plan(StreamQualitySettings("economy", 60, 32_000_000), source)
        assertEquals(30, plan.maxFps); assertEquals(2_000_000, plan.maxBitrate)
        assertEquals(960, source.width); assertEquals(540, source.height)
    }
    @Test fun `explicit low limits and codec bitrate ceiling are respected`() {
        val plan = StreamQualityPolicy.plan(StreamQualitySettings("detail", 1, 100_000), source)
        assertEquals(1, plan.maxFps); assertEquals(100_000, plan.maxBitrate)
        assertEquals(900_000, StreamQualityPolicy.plan(StreamQualitySettings("detail"), source.copy(codecMaxBitrate = 900_000)).maxBitrate)
    }
    @Test fun `invalid persisted or remote preferences are rejected rather than silently widened`() {
        for (fps in listOf(-1, 0, 61, Int.MAX_VALUE))
            assertThrows(IllegalArgumentException::class.java) { StreamQualitySettings(maxFps = fps) }
        for (bitrate in listOf(-1, 99_999, 32_000_001, Int.MAX_VALUE))
            assertThrows(IllegalArgumentException::class.java) { StreamQualitySettings(maxBitrateBps = bitrate) }
        assertThrows(IllegalArgumentException::class.java) { StreamQualitySettings("lossless") }
    }
    @Test fun `large source arithmetic stays bounded without integer overflow`() {
        assertEquals(32_000_000, StreamQualityPolicy.plan(StreamQualitySettings("detail"),
            StreamQualityPolicy.Source(8192, 8192, 240f)).maxBitrate)
    }
    @Test fun `congestion reduces source bitrate before encoding and growth is gradual`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings("detail"), source))
        assertEquals(500_000, governor.observe(500_000, 15, 1000)!!.bitrate)
        assertNull(governor.observe(20_000_000, 60, 1500))
        val grown = governor.observe(20_000_000, 60, 2000)!!
        assertEquals(600_000, grown.bitrate); assertEquals(60, grown.fps)
    }
    @Test fun `rapid estimates coalesce through time budget instead of hammering the codec`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings(), source))
        var changed = 0
        repeat(10_000) { if (governor.observe(32_000_000, 60, 1000) != null) changed++ }
        assertEquals(1, changed)
    }
    @Test fun `observed input cadence cannot recursively collapse the configured source fps`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings(), source))
        for ((index, observed) in listOf(39, 28, 20, 10, 7, 5, 1).withIndex()) {
            assertNull(governor.observe(2_000_000, observed, index * 1000L))
            assertEquals(60, governor.rate.fps)
        }
        assertEquals(500_000, governor.observe(500_000, 1, 8000)!!.bitrate)
        assertEquals(60, governor.rate.fps)
    }
    @Test fun `explicit low source fps remains bounded independently of the observed input estimate`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings("economy", 24), source))
        for ((index, observed) in listOf(60, 24, 10, 1, 60).withIndex()) {
            governor.observe(500_000, observed, index * 1000L)
            assertEquals(24, governor.rate.fps)
        }
    }
    @Test fun `zero allocation cannot stop the capture needed by another fallback viewer`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings(), source))
        val before = governor.rate
        assertNull(governor.observe(0, 0, 0)); assertNull(governor.observe(1_000_000, 0, 1))
        assertEquals(before, governor.rate)
    }
    @Test fun `invalid estimates and clock regression never raise an existing source budget`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings(), source))
        governor.observe(100_000, 1, 1000)
        val before = governor.rate
        assertNull(governor.observe(Int.MAX_VALUE, 60, 2000))
        assertNull(governor.observe(1_000_000, 241, 2000))
        assertNull(governor.observe(1_000_000, 60, -1))
        assertNull(governor.observe(32_000_000, 60, 999))
        assertEquals(before, governor.rate)
    }
    @Test fun `changing quality replaces the old ceiling and recovery cannot exceed the new limit`() {
        val governor = DirectSourceRateGovernor(StreamQualityPolicy.plan(StreamQualitySettings("detail"), source))
        governor.configure(StreamQualityPolicy.plan(StreamQualitySettings("economy", 10, 750_000), source))
        repeat(100) { governor.observe(32_000_000, 60, it * 1000L) }
        assertEquals(750_000, governor.rate.bitrate); assertEquals(10, governor.rate.fps)
    }
    @Test fun `avc admission counts picture cadence and bitrate instead of assuming level31`() {
        assertEquals(AvcLevel.L31, AvcLevel.required(960, 540, 30, 4_000_000))
        assertEquals(AvcLevel.L32, AvcLevel.required(960, 540, 60, 12_441_600))
        assertEquals(AvcLevel.L41, AvcLevel.required(960, 540, 60, 32_000_000))
        assertEquals(AvcLevel.L42, AvcLevel.required(1920, 1080, 60, 32_000_000))
        assertEquals("42e02a", AvcLevel.L42.profileLevelId)
    }
}
