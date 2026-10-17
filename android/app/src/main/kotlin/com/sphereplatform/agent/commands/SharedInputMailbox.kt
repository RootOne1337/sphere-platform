package com.sphereplatform.agent.commands

/**
 * Callback-to-native actor mailbox: ten registered clients, four pointer entries and
 * 32 keyboard entries each, one drain actor. A modifier chord is several ordered
 * edges; applying the old three-event pointer budget to it retired healthy input.
 * No coroutine, closure or unbounded list is created per MOVE. Ordering uses APK arrival order.
 * Coalescing changes the retained event's arrival order; it cannot overtake another client's DOWN.
 */
internal class SharedInputMailbox {
    companion object { const val PER_PARTICIPANT = 4; const val KEYBOARD_PENDING = 32 }
    enum class Admission { QUEUED, COALESCED, UNREGISTERED, RETIRED, INVALID, OVERFLOW }
    sealed interface Work {
        data class Input(val event: SharedPointerArbiter.Event) : Work
        data class Close(val participant: String) : Work
    }
    private data class Entry(val order: Long, val event: SharedPointerArbiter.Event)
    private class Slot {
        val pending = ArrayDeque<Entry>()
        var sequence = 0
        var closeOrder: Long? = null
    }
    private val slots = LinkedHashMap<String, Slot>()
    private var order = 0L

    @Synchronized fun register(participant: String): Boolean {
        if (!participant.matches(Regex("[A-Za-z0-9_-]{8,128}")) || participant in slots
            || slots.size >= SharedPointerArbiter.MAX_PARTICIPANTS || order == Long.MAX_VALUE) return false
        slots[participant] = Slot()
        return true
    }

    @Synchronized fun offer(event: SharedPointerArbiter.Event): Admission {
        val slot = slots[event.participant] ?: return Admission.UNREGISTERED
        if (slot.closeOrder != null) return Admission.RETIRED
        if (event.sequence < 1 || event.sequence <= slot.sequence || event.gesture !in 0..Int.MAX_VALUE.toLong()
            || event.action !in setOf(0, 1, 2, 3, 4, 5, RemoteKeyboardCommand.ACTION) || event.receivedAtMs < 0
            || (if (event.action == RemoteKeyboardCommand.ACTION) event.keyboard == null || event.gesture != 0L
                else if (event.action == RootTouchSession.KEY_TAP) event.gesture != 0L
                || !RootTouchSession.supportedKey(event.x) || event.y != 0
                else event.x !in 0..16383 || event.y !in 0..16383) || order == Long.MAX_VALUE) {
            retire(event.participant)
            return Admission.INVALID
        }
        val tail = slot.pending.lastOrNull()
        val replaceable = tail?.event?.action == event.action && tail.event.gesture == event.gesture
            && event.action in setOf(RootTouchSession.MOVE, RootTouchSession.HEARTBEAT)
        val keyboard = event.action == RemoteKeyboardCommand.ACTION
        val terminal = if (keyboard) event.keyboard?.operation in setOf(RemoteKeyboardCommand.Operation.KEY_UP,
            RemoteKeyboardCommand.Operation.RESET, RemoteKeyboardCommand.Operation.FINISH)
            else event.action == RootTouchSession.UP || event.action == RootTouchSession.CANCEL
        val sizeAfterReplacement = slot.pending.count { (it.event.action == RemoteKeyboardCommand.ACTION) == keyboard }
            - if (replaceable) 1 else 0
        val budget = if (keyboard) KEYBOARD_PENDING else PER_PARTICIPANT
        if (sizeAfterReplacement >= if (terminal) budget else budget - 1) {
            retire(event.participant)
            return Admission.OVERFLOW
        }
        if (replaceable) slot.pending.removeLast()
        slot.pending.addLast(Entry(++order, event))
        slot.sequence = event.sequence
        return if (replaceable) Admission.COALESCED else Admission.QUEUED
    }

    /** Local close/overflow replaces this client's unsent input with one exact cleanup intent. */
    @Synchronized fun retire(participant: String): Boolean {
        val slot = slots[participant] ?: return false
        if (slot.closeOrder == null) {
            slot.pending.clear()
            slot.closeOrder = if (order == Long.MAX_VALUE) order else ++order
        }
        return true
    }

    @Synchronized fun poll(): Work? {
        val chosen = slots.entries.filter { (_, slot) -> slot.closeOrder != null || slot.pending.isNotEmpty() }
            .minByOrNull { (_, slot) -> slot.closeOrder ?: checkNotNull(slot.pending.firstOrNull()).order }
            ?: return null
        val slot = chosen.value
        if (slot.closeOrder != null) {
            slots.remove(chosen.key)
            return Work.Close(chosen.key)
        }
        return slot.pending.removeFirstOrNull()?.let { Work.Input(it.event) }
    }

    /** Called only after the native actor has completed this participant's cleanup. */
    @Synchronized fun remove(participant: String) { slots.remove(participant) }
    @Synchronized fun clear() { slots.clear() }
    @Synchronized fun participantCount() = slots.size
    @Synchronized fun pendingCount() = slots.values.sumOf { if (it.closeOrder != null) 1 else it.pending.size }
}
