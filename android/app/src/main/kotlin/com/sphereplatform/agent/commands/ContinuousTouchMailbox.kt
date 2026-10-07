package com.sphereplatform.agent.commands

/** Immutable server/capture ownership. Root availability alone must never create this binding. */
internal data class TouchBinding(
    val owner: String,
    val captureEpoch: String,
    val width: Int,
    val height: Int,
    val rotation: Int,
) {
    init {
        require(owner.matches(Regex("[A-Za-z0-9_-]{8,128}")) && captureEpoch.matches(Regex("[A-Za-z0-9_-]{8,128}")))
        require(width in 1..16384 && height in 1..16384 && rotation in 0..3)
    }
}

internal data class TouchSample(
    val sequence: Int,
    val gesture: Long,
    val action: Int,
    val x: Int,
    val y: Int,
    /** Receipt on this Android, never browser wall clock or an untrusted wire timestamp. */
    val receivedAtMs: Long,
)

/** At most four pending events. MOVE coalescing never crosses DOWN/UP/CANCEL barriers. */
internal class ContinuousTouchMailbox(val binding: TouchBinding, openedAtMs: Long) {
    enum class Admission { QUEUED, COALESCED, WRONG_OWNER, RETIRED, INVALID, OVERFLOW }
    private val pending = ArrayDeque<TouchSample>()
    private var lastSequence = 0
    private var gesture = 0L
    private var lastGesture = 0L
    private var held = false
    private var lastReceipt = openedAtMs
    private var retired = false

    init { require(openedAtMs >= 0) }

    @Synchronized
    fun offer(owner: String, captureEpoch: String, sample: TouchSample): Admission {
        // Another viewer cannot cancel the actual owner by submitting a bad packet.
        if (owner != binding.owner) return Admission.WRONG_OWNER
        if (retired) return Admission.RETIRED
        val invalid = captureEpoch != binding.captureEpoch || sample.receivedAtMs < lastReceipt
            || sample.receivedAtMs - lastReceipt >= RootTouchSession.LEASE_MS
            || sample.sequence <= lastSequence || sample.sequence < 1 || sample.action !in 0..4
            || sample.x !in 0 until binding.width || sample.y !in 0 until binding.height
            || when (sample.action) {
                RootTouchSession.DOWN -> held || sample.gesture <= lastGesture
                RootTouchSession.HEARTBEAT -> sample.gesture != if (held) gesture else 0L
                else -> !held || sample.gesture != gesture
            }
        if (invalid) { retire(); return Admission.INVALID }

        val tail = pending.lastOrNull()
        // Only adjacent MOVE samples can be replaced; preserve gesture order and terminal events.
        val coalesced = sample.action == RootTouchSession.MOVE && tail?.action == RootTouchSession.MOVE
            && tail.gesture == sample.gesture
        // An idle or held heartbeat is also replaceable only by another adjacent heartbeat.
        val heartbeat = sample.action == RootTouchSession.HEARTBEAT && tail?.action == RootTouchSession.HEARTBEAT
        if (coalesced || heartbeat) pending.removeLast()
        // Reserve one slot for UP/CANCEL. Overflow fails closed rather than dropping a terminal event.
        val limit = if (sample.action == RootTouchSession.UP || sample.action == RootTouchSession.CANCEL) CAPACITY else CAPACITY - 1
        if (pending.size >= limit) { retire(); return Admission.OVERFLOW }
        // A later browser heartbeat cannot freshen an old movement blocked behind an injector.
        pending.addLast(sample)
        lastSequence = sample.sequence
        lastReceipt = sample.receivedAtMs
        when (sample.action) {
            RootTouchSession.DOWN -> { gesture = sample.gesture; lastGesture = gesture; held = true }
            RootTouchSession.UP, RootTouchSession.CANCEL -> held = false
        }
        return if (coalesced || heartbeat) Admission.COALESCED else Admission.QUEUED
    }

    @Synchronized
    fun poll(now: Long): TouchSample? {
        if (expired(now)) return null
        val sample = pending.firstOrNull() ?: return null
        if (now < sample.receivedAtMs || now - sample.receivedAtMs >= MAX_PENDING_AGE_MS) {
            retire()
            return null
        }
        return pending.removeFirst()
    }

    @Synchronized
    fun expired(now: Long): Boolean {
        if (!retired && (now < lastReceipt || now - lastReceipt >= RootTouchSession.LEASE_MS)) retire()
        return retired
    }

    @Synchronized fun retire() { retired = true; pending.clear() }
    @Synchronized fun isRetired(): Boolean = retired
    @Synchronized fun size(): Int = pending.size

    companion object {
        const val CAPACITY = 4
        const val MAX_PENDING_AGE_MS = 500L
    }
}
