package com.sphereplatform.agent.direct

/**
 * V2 authority delivered once over authenticated signaling, bound to an exact DTLS peer,
 * device instance and capture. This is separate from the 1500 ms local held-touch watchdog.
 * There is no wire parser here. The offer adapter must construct it only from an
 * authenticated server grant after RBAC and DTLS binding checks, never browser claims.
 */
internal class AutonomousSessionGrant(
    val session: String,
    val deviceInstance: String,
    val captureEpoch: String,
    val mayControl: Boolean,
    val issuedAtMs: Long,
    lifetimeMs: Long,
) {
    companion object {
        const val MAX_LIFETIME_MS = 8 * 60 * 60 * 1000L
        const val SETUP_TIMEOUT_MS = 30_000L
        private val ID = Regex("[A-Za-z0-9_-]{8,128}")
    }
    enum class End { SETUP_EXPIRED, EXPIRED, CLOCK_REGRESSION, PEER_LOST, CAPTURE_CHANGED, INSTANCE_CHANGED, REVOKED }
    val expiresAtMs: Long
    var established = false
        private set
    var brokerAvailable = true
        private set
    var ended: End? = null
        private set
    private var lastTime = issuedAtMs

    init {
        require(ID.matches(session) && ID.matches(deviceInstance) && ID.matches(captureEpoch))
        require(issuedAtMs >= 0 && lifetimeMs in 1..MAX_LIFETIME_MS && issuedAtMs <= Long.MAX_VALUE - lifetimeMs)
        expiresAtMs = issuedAtMs + lifetimeMs
    }

    /** Called only after this negotiated DTLS peer actually connected, never after a server ACK. */
    fun establish(peerSession: String, instance: String, capture: String, now: Long): Boolean {
        if (peerSession != session || !valid(instance, capture, now)) return false
        established = true
        return true
    }

    fun valid(instance: String, capture: String, now: Long): Boolean {
        if (ended != null) return false
        val failure = when {
            now < lastTime -> End.CLOCK_REGRESSION
            instance != deviceInstance -> End.INSTANCE_CHANGED
            capture != captureEpoch -> End.CAPTURE_CHANGED
            now >= expiresAtMs -> End.EXPIRED
            !established && now - issuedAtMs >= SETUP_TIMEOUT_MS -> End.SETUP_EXPIRED
            else -> null
        }
        lastTime = maxOf(lastTime, now)
        if (failure != null) revoke(failure)
        return failure == null
    }

    /** An unavailable broker is not evidence of lost DTLS consent or changed permissions. */
    fun brokerLost(now: Long) {
        brokerAvailable = false
        if (!valid(deviceInstance, captureEpoch, now)) return
        if (!established) revoke(End.PEER_LOST)
    }

    /** A transport generation is not device identity. Reconciliation uses the stable instance. */
    fun brokerRestored(instance: String, capture: String, now: Long): Boolean {
        if (!valid(instance, capture, now)) return false
        brokerAvailable = true
        return true
    }

    fun maySendInput(instance: String, capture: String, now: Long): Boolean =
        valid(instance, capture, now) && established && mayControl

    /** Peer loss, explicit revocation, capture loss and service/identity changes remain terminal. */
    fun revoke(reason: End = End.REVOKED) { if (ended == null) ended = reason }
}
