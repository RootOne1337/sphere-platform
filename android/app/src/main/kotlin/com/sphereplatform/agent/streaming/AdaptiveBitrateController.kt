package com.sphereplatform.agent.streaming

import timber.log.Timber

/**
 * Adaptive bitrate controller that reacts to WebSocket send failures
 * (frame drops) reported by [StreamingManagerImpl].
 *
 * Algorithm:
 * - 3 consecutive drops → reduce bitrate by 20 % (floor: [minBitrate])
 * - 90 consecutive local WebSocket admissions → restore by 5 % (ceiling: [maxBitrate])
 * Local queue admission is not a server receipt or a measure of network capacity.
 */
class AdaptiveBitrateController(
    private val encoder: H264Encoder,
    private val minBitrate: Int = 500_000,
    private val maxBitrate: Int = 4_000_000,
    initialBitrate: Int = 0,
) {
    // FIX H3: Инициализируем из фактического битрейта энкодера, а не хардкоденных 2Mbps.
    // Ранее ABR думал currentBitrate=2Mbps, а энкодер стартовал на 1.5Mbps → рассинхрон.
    private var currentBitrate = if (initialBitrate > 0) initialBitrate else 2_000_000
    private var consecutiveDrops = 0
    // Count-based debounce: at 30 media packets/s this is approximately 3s.
    // At a lower source cadence recovery takes longer; this is not a wall-clock timer.
    private var successfulDeliveries = 0
    private val MIN_DELIVERIES_BEFORE_RESTORE = 90 // ~3 секунды при 30 FPS

    fun onFrameDropDetected() {
        consecutiveDrops++
        successfulDeliveries = 0 // Сброс при drop
        if (consecutiveDrops >= 3) {
            val newBitrate = (currentBitrate * 0.8).toInt().coerceAtLeast(minBitrate)
            if (newBitrate != currentBitrate) {
                currentBitrate = newBitrate
                encoder.adjustBitrate(currentBitrate)
                Timber.d("ABR: bitrate reduced to ${currentBitrate / 1000} kbps")
            }
        }
    }

    fun onSuccessfulDelivery() {
        consecutiveDrops = 0
        successfulDeliveries++
        // Keep the existing admission budget before requesting another increase.
        if (successfulDeliveries < MIN_DELIVERIES_BEFORE_RESTORE) return
        successfulDeliveries = 0
        val newBitrate = (currentBitrate * 1.05).toInt().coerceAtMost(maxBitrate)
        // A fixed 100kbps threshold made every target <=2Mbps unrecoverable:
        // e.g. 1.2Mbps +5% is only 60kbps. Debounce already limits updates.
        if (newBitrate > currentBitrate) {
            currentBitrate = newBitrate
            encoder.adjustBitrate(currentBitrate)
            Timber.d("ABR: bitrate restored to ${currentBitrate / 1000} kbps")
        }
    }

    val currentBitrateBps: Int get() = currentBitrate
}
