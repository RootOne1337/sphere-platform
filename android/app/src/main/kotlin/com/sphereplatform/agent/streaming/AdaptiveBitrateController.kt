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
) {
    private var currentBitrate = 2_000_000
    private var consecutiveDrops = 0

    fun onFrameDropDetected() {
        consecutiveDrops++
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
        val newBitrate = (currentBitrate * 1.05).toInt().coerceAtMost(maxBitrate)
        if (newBitrate > currentBitrate + 100_000) {
            currentBitrate = newBitrate
            encoder.adjustBitrate(currentBitrate)
            Timber.d("ABR: bitrate restored to ${currentBitrate / 1000} kbps")
        }
    }

    val currentBitrateBps: Int get() = currentBitrate
}
