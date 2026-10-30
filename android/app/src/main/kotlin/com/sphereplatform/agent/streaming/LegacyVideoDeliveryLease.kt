package com.sphereplatform.agent.streaming

/** A direct peer may suppress only its duplicate WS copy, never the coded RTP chain.
 * State belongs to one capture/peer owner. Missing or expired renewal fails open.
 */
internal class LegacyVideoDeliveryLease {
    companion object {
        const val MAX_SUPPRESSION_MS = 10_000
        const val NEW_LEGACY_VIEWER_GRACE_MS = 12_000L
    }

    data class Decision(val sendLegacy: Boolean, val requestKeyFrame: Boolean)
    private var suppressionUntil: Long? = null
    private var requiredUntil = 0L
    private var observedAt: Long? = null
    private var previouslySending = true

    @Synchronized
    fun renew(enabled: Boolean, now: Long, ttlMs: Int): Boolean {
        if (now < 0 || ttlMs !in 1..MAX_SUPPRESSION_MS || now > Long.MAX_VALUE - ttlMs) {
            suppressionUntil = null
            return false
        }
        suppressionUntil = if (enabled) null else now + ttlMs
        return true
    }

    /** New fallback viewers must receive headers/IDR before any late OFF renewal. */
    @Synchronized
    fun requireLegacy(now: Long) {
        suppressionUntil = null
        requiredUntil = if (now >= 0 && now <= Long.MAX_VALUE - NEW_LEGACY_VIEWER_GRACE_MS)
            now + NEW_LEGACY_VIEWER_GRACE_MS else Long.MAX_VALUE
    }

    @Synchronized
    fun observe(now: Long): Decision {
        val previous = observedAt
        if (now < 0 || previous != null && now < previous) {
            suppressionUntil = null
            requiredUntil = 0
        }
        observedAt = now
        val send = now < requiredUntil || suppressionUntil?.let { now >= it } != false
        val result = Decision(send, send && !previouslySending)
        previouslySending = send
        return result
    }
}
