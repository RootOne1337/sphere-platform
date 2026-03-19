package com.sphereplatform.agent.streaming

import timber.log.Timber

/**
 * Adaptive bitrate controller that reacts to WebSocket send failures
 * (frame drops) reported by [StreamingManagerImpl].
 *
 * Algorithm:
 * - 3 consecutive drops → reduce bitrate by 20 % (floor: [minBitrate])
 * - Successful delivery → gradually restore bitrate by 5 % (ceiling: [maxBitrate])
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
    // FIX AUDIT-2.6: Debounce для restore — не повышаем чаще раза в 3 секунды.
    // При 30 FPS без debounce = удвоение битрейта за ~15с, что вызывает oscillation.
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
        // FIX AUDIT-2.6: Восстановление не чаще раза в ~3 секунды
        if (successfulDeliveries < MIN_DELIVERIES_BEFORE_RESTORE) return
        successfulDeliveries = 0
        val newBitrate = (currentBitrate * 1.05).toInt().coerceAtMost(maxBitrate)
        if (newBitrate > currentBitrate + 100_000) {
            currentBitrate = newBitrate
            encoder.adjustBitrate(currentBitrate)
            Timber.d("ABR: bitrate restored to ${currentBitrate / 1000} kbps")
        }
    }

    val currentBitrateBps: Int get() = currentBitrate
}
