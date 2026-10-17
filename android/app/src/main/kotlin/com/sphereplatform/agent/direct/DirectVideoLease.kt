package com.sphereplatform.agent.direct

/** Monotonic, exact-peer lease. Expired ownership can never be renewed. */
internal class DirectVideoLease(private val startedAt: Long, ttlMs: Int, val live: Boolean) {
    companion object { const val MAX_LIFETIME_MS = 8 * 60 * 60 * 1000L }
    var expiresAt: Long = startedAt + ttlMs
        private set
    private var sequence = 0
    private var lastRenewedAt = startedAt

    fun valid(now: Long): Boolean = now >= startedAt && now < expiresAt && now - startedAt < MAX_LIFETIME_MS

    fun renew(sequence: Int, ttlMs: Int, receivedAt: Long, processedAt: Long): Boolean {
        if (!live || sequence !in 1..1000000 || sequence <= this.sequence || ttlMs !in 1..30000 ||
            receivedAt < lastRenewedAt || processedAt < receivedAt || !valid(receivedAt) || !valid(processedAt) ||
            receivedAt + ttlMs <= processedAt) return false
        expiresAt = minOf(receivedAt + ttlMs, startedAt + MAX_LIFETIME_MS)
        this.sequence = sequence
        lastRenewedAt = receivedAt
        return true
    }
}
