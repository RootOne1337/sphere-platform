package com.sphereplatform.agent.commands

/**
 * V2 device-local arbitration. Only an authenticated session grant may attach a participant.
 * A single bounded actor must call this object; native delivery is acknowledged before takeover.
 * ALIVE is an APK liveness result, never an InputDispatcher execution acknowledgement.
 */
internal class SharedPointerArbiter(
    private val width: Int,
    private val height: Int,
    private val uptime: () -> Long,
    private val deliver: suspend (NativeAction) -> Boolean,
) {
    companion object {
        const val MAX_PARTICIPANTS = 10
        const val MAX_GRANT_MS = 8 * 60 * 60 * 1000L
        const val MAX_EVENT_AGE_MS = 500L
    }

    enum class Outcome { APPLIED, ALIVE, INTERRUPTED, CLOSED, DENIED, EXPIRED, INVALID, UNKNOWN, BUSY }
    data class Notice(val participant: String, val sequence: Int, val gesture: Long, val outcome: Outcome)
    data class Event(val participant: String, val sequence: Int, val gesture: Long,
                     val action: Int, val x: Int, val y: Int, val receivedAtMs: Long)
    data class NativeAction(val action: Int, val gesture: Long, val x: Int, val y: Int)
    private class Participant(val id: String, val expiresAtMs: Long, val control: Boolean, now: Long) {
        var sequence = 0
        var lastGesture = 0L
        var gesture: Long? = null
        var interruptedGesture: Long? = null
        var lastSeenMs = now
    }
    private data class Held(val participant: Participant, val gesture: Long, val nativeGesture: Long, var x: Int, var y: Int)
    private val participants = LinkedHashMap<String, Participant>()
    private var held: Held? = null
    private var nativeGesture = 0L
    private var lastTime = uptime().also { require(it >= 0) }
    private var operating = false
    var fenced = false
        private set
    val participantCount get() = participants.size
    val heldParticipant get() = held?.participant?.id
    val nativeHeldGesture get() = held?.nativeGesture ?: 0L

    init { require(width in 1..16384 && height in 1..16384) }

    /** Admission does not acquire the pointer, replace another participant or revive an old grant. */
    fun attach(participant: String, expiresAtMs: Long, control: Boolean): Boolean {
        val now = uptime()
        if (fenced || operating) return false
        if (now < lastTime) { fenceAll(); return false }
        if (!participant.matches(Regex("[A-Za-z0-9_-]{8,128}"))
            || expiresAtMs <= now || expiresAtMs - now > MAX_GRANT_MS
            || participant in participants || participants.size >= MAX_PARTICIPANTS) return false
        lastTime = now
        participants[participant] = Participant(participant, expiresAtMs, control, now)
        return true
    }

    suspend fun offer(event: Event): List<Notice> {
        if (operating) return listOf(event.notice(Outcome.BUSY))
        operating = true
        try {
            val now = checkedTime() ?: return fenceAll()
            val participant = participants[event.participant] ?: return listOf(event.notice(Outcome.DENIED))
            if (fenced || !participant.control) return listOf(event.notice(Outcome.DENIED))
            if (now >= participant.expiresAtMs || now - participant.lastSeenMs >= RootTouchSession.LEASE_MS)
                return removeInternal(participant, Outcome.EXPIRED)
            if (event.receivedAtMs > now || now - event.receivedAtMs >= MAX_EVENT_AGE_MS)
                return reject(participant, event, Outcome.EXPIRED)
            if (event.sequence < 1 || event.sequence <= participant.sequence || event.gesture !in 0..Int.MAX_VALUE.toLong()
                || event.action !in RootTouchSession.DOWN..RootTouchSession.KEY_TAP
                || (if (event.action == RootTouchSession.KEY_TAP) event.gesture != 0L
                    || !RootTouchSession.supportedKey(event.x) || event.y != 0
                    else event.x !in 0 until width || event.y !in 0 until height))
                return reject(participant, event, Outcome.INVALID)
            participant.sequence = event.sequence
            participant.lastSeenMs = now
            if (event.action == RootTouchSession.KEY_TAP) {
                val notices = mutableListOf<Notice>()
                held?.let { previous ->
                    if (!dispatch(NativeAction(RootTouchSession.CANCEL, previous.nativeGesture, previous.x, previous.y))) return fenceAll()
                    previous.participant.gesture = null
                    previous.participant.interruptedGesture = previous.gesture
                    held = null
                    notices += Notice(previous.participant.id, previous.participant.sequence, previous.gesture, Outcome.INTERRUPTED)
                }
                val afterCancel = checkedTime() ?: return notices + fenceAll()
                if (afterCancel >= participant.expiresAtMs || afterCancel - event.receivedAtMs >= MAX_EVENT_AGE_MS)
                    return notices + reject(participant, event, Outcome.EXPIRED)
                if (!dispatch(NativeAction(RootTouchSession.KEY_TAP, 0, event.x, event.y))) return notices + fenceAll()
                return notices + event.notice(Outcome.APPLIED)
            }
            if (participant.gesture == null && event.gesture != 0L && event.gesture == participant.interruptedGesture)
                return listOf(event.notice(Outcome.INTERRUPTED))
            if (event.action == RootTouchSession.HEARTBEAT) {
                return if (event.gesture == (participant.gesture ?: 0L)) listOf(event.notice(Outcome.ALIVE))
                else reject(participant, event, Outcome.INVALID)
            }
            if (event.action == RootTouchSession.DOWN) {
                if (participant.gesture != null || event.gesture <= participant.lastGesture)
                    return reject(participant, event, Outcome.INVALID)
                val notices = mutableListOf<Notice>()
                val previous = held
                if (previous != null) {
                    if (!dispatch(NativeAction(RootTouchSession.CANCEL, previous.nativeGesture, previous.x, previous.y))) return fenceAll()
                    previous.participant.gesture = null
                    previous.participant.interruptedGesture = previous.gesture
                    held = null
                    notices += Notice(previous.participant.id, previous.participant.sequence, previous.gesture, Outcome.INTERRUPTED)
                }
                // A slow CANCEL cannot carry a new DOWN past its own grant or input deadline.
                val afterCancel = checkedTime() ?: return notices + fenceAll()
                if (afterCancel >= participant.expiresAtMs || afterCancel - event.receivedAtMs >= MAX_EVENT_AGE_MS) {
                    notices += reject(participant, event, Outcome.EXPIRED)
                    return notices
                }
                if (nativeGesture == Long.MAX_VALUE) return notices + fenceAll()
                val nextGesture = ++nativeGesture
                if (!dispatch(NativeAction(RootTouchSession.DOWN, nextGesture, event.x, event.y))) return notices + fenceAll()
                participant.gesture = event.gesture
                participant.lastGesture = event.gesture
                held = Held(participant, event.gesture, nextGesture, event.x, event.y)
                return notices + event.notice(Outcome.APPLIED)
            }
            val current = held
            if (current == null || current.participant !== participant || participant.gesture != event.gesture)
                return reject(participant, event, Outcome.INVALID)
            if (!dispatch(NativeAction(event.action, current.nativeGesture, event.x, event.y))) return fenceAll()
            current.x = event.x; current.y = event.y
            if (event.action == RootTouchSession.UP || event.action == RootTouchSession.CANCEL) {
                held = null
                participant.gesture = null
            }
            return listOf(event.notice(Outcome.APPLIED))
        } finally { operating = false }
    }

    /** Expiry/close isolates one peer. An uncertain native CANCEL fences the shared injector. */
    suspend fun remove(participant: String): List<Notice> {
        if (operating) return listOf(Notice(participant, 0, 0, Outcome.BUSY))
        operating = true
        try {
            if (checkedTime() == null) return fenceAll()
            return participants[participant]?.let { removeInternal(it, Outcome.CLOSED) } ?: emptyList()
        } finally { operating = false }
    }

    suspend fun expire(): List<Notice> {
        if (operating) return emptyList()
        operating = true
        try {
            val now = checkedTime() ?: return fenceAll()
            val expired = participants.values.filter { now >= it.expiresAtMs || now - it.lastSeenMs >= RootTouchSession.LEASE_MS }
            val notices = mutableListOf<Notice>()
            for (participant in expired) {
                notices += removeInternal(participant, Outcome.EXPIRED)
                if (fenced) break
            }
            return notices
        } finally { operating = false }
    }

    private suspend fun reject(participant: Participant, event: Event, outcome: Outcome): List<Notice> {
        val removed = removeInternal(participant, outcome)
        return if (fenced) removed else removed.map { if (it.participant == event.participant) event.notice(outcome) else it }
    }

    private suspend fun removeInternal(participant: Participant, outcome: Outcome): List<Notice> {
        val current = held
        if (current?.participant === participant) {
            if (!dispatch(NativeAction(RootTouchSession.CANCEL, current.nativeGesture, current.x, current.y))) return fenceAll()
            held = null
        }
        participants.remove(participant.id)
        return listOf(Notice(participant.id, participant.sequence, participant.gesture ?: 0L, outcome))
    }

    private suspend fun dispatch(action: NativeAction): Boolean = try { deliver(action) } catch (_: Exception) { false }
    private fun checkedTime(): Long? {
        val now = uptime()
        if (now < lastTime) return null
        lastTime = now
        return now
    }
    private fun fenceAll(): List<Notice> {
        fenced = true
        // Only confirmed external pipe teardown may reset this object; UNKNOWN is never APPLIED.
        return participants.values.map { Notice(it.id, it.sequence, it.gesture ?: 0L, Outcome.UNKNOWN) }.also {
            participants.clear(); held = null
        }
    }
    private fun Event.notice(outcome: Outcome) = Notice(participant, sequence, gesture, outcome)
}
