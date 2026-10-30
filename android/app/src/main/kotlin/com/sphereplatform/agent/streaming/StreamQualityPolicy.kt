package com.sphereplatform.agent.streaming

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.roundToInt

/** Device-wide source policy. RTP bandwidth estimates are not a claim of a LAN route. */
@Serializable
data class StreamQualitySettings(
    val profile: String = "auto",
    @SerialName("max_fps") val maxFps: Int? = null,
    @SerialName("max_bitrate_bps") val maxBitrateBps: Int? = null,
) {
    init {
        require(profile in setOf("auto", "detail", "economy"))
        require(maxFps == null || maxFps in 1..60)
        require(maxBitrateBps == null || maxBitrateBps in 100_000..32_000_000)
    }
}

internal object StreamQualityPolicy {
    data class Source(val width: Int, val height: Int, val refreshRate: Float,
                      val codecMaxFps: Int = 60, val codecMaxBitrate: Int = 32_000_000) {
        init {
            require(width in 1..8192 && height in 1..8192)
            require(codecMaxFps in 1..60 && codecMaxBitrate > 0)
        }
        val sourceFps: Int get() = if (refreshRate.isFinite() && refreshRate > 0)
            refreshRate.roundToInt().coerceIn(1, 240) else 30
        val maximumFps: Int get() = minOf(sourceFps, codecMaxFps, 60)
    }
    data class Plan(val maxFps: Int, val maxBitrate: Int, val initialBitrate: Int, val minBitrate: Int)

    fun plan(settings: StreamQualitySettings, source: Source): Plan {
        val fps = minOf(settings.maxFps ?: source.maximumFps, source.maximumFps,
            if (settings.profile == "economy") 30 else 60)
        // Budget scales with real pixels and cadence. No upscaling or second encoder.
        val detailBudget = (source.width.toLong() * source.height * fps * 2 / 5)
            .coerceIn(500_000L, 32_000_000L).toInt()
        val ceiling = minOf(settings.maxBitrateBps ?: detailBudget, source.codecMaxBitrate,
            if (settings.profile == "economy") 2_000_000 else 32_000_000)
        val floor = minOf(100_000, ceiling)
        val initial = if (settings.profile == "detail") ceiling else minOf(2_000_000, ceiling)
        return Plan(fps, ceiling, initial, floor)
    }
}

/** Smooth source changes before encoding; never discard a coded reference picture. */
internal class DirectSourceRateGovernor(private var plan: StreamQualityPolicy.Plan) {
    data class Rate(val bitrate: Int, val fps: Int)
    private var current = Rate(plan.initialBitrate, plan.maxFps)
    private var observedAt: Long? = null
    private var changedAt: Long? = null
    val rate: Rate get() = current

    fun configure(value: StreamQualityPolicy.Plan): Rate {
        plan = value
        current = Rate(value.initialBitrate, value.maxFps)
        changedAt = null
        return current
    }

    fun refused(actualBitrate: Int, actualFps: Int) {
        require(actualBitrate > 0 && actualFps in 1..60)
        current = Rate(actualBitrate, actualFps)
    }

    fun observe(bitrate: Int, fps: Int, nowMs: Long): Rate? {
        if (nowMs < 0 || bitrate !in 0..100_000_000 || fps !in 0..240) return null
        if (observedAt?.let { nowMs < it } == true) { observedAt = nowMs; changedAt = null; return null }
        observedAt = nowMs
        // Zero is RTP pause, not permission to stop capture needed by fallback viewers.
        if (bitrate == 0 || fps == 0) return null
        val wanted = bitrate.coerceIn(plan.minBitrate, plan.maxBitrate)
        // WebRTC derives this encoder estimate from its observed input cadence.
        // Feeding that estimate back into the capture throttle creates a loop:
        // scheduling jitter lowers the estimate, which lowers the source again.
        // Source cadence belongs to the display/codec/user policy; the network
        // allocation adapts bitrate before encoding without throttling by input FPS.
        val targetFps = plan.maxFps
        val elapsed = changedAt?.let { nowMs - it }
        val reducing = wanted < current.bitrate * 85L / 100
        if (elapsed != null && elapsed < if (reducing) 250 else 1000) return null
        // Fast congestion response, gradual growth: no repeated codec changes per packet.
        val nextBitrate = if (wanted > current.bitrate)
            minOf(wanted, maxOf(current.bitrate + 100_000, current.bitrate * 6 / 5)) else wanted
        val next = Rate(nextBitrate, targetFps)
        if (next == current) return null
        changedAt = nowMs
        current = next
        return next
    }
}
