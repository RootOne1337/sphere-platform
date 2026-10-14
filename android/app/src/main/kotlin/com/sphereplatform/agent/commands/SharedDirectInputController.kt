package com.sphereplatform.agent.commands

import com.sphereplatform.agent.direct.DirectInputChannel
import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.StreamPoint
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.*
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** One native pipe and one arrival-order actor for ten authenticated media peers.
 * No input is replayed. Closing one participant cancels only its held gesture.
 * Data-channel readiness never grants control: the authenticated server offer must
 * explicitly call [grant], and the exact peer/capture grant remains current.
 */
internal class SharedDirectInputController(
    private val scope: CoroutineScope,
    private val factory: TouchPipeFactory,
    private val capture: () -> CaptureInputSession?,
    private val uptime: () -> Long,
    dispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val diagnostics: NativeInputDiagnostics = NativeInputDiagnostics(uptime),
    private val keyboard: RemoteKeyboardAdapter? = null,
) {
    private class Participant(val channel: DirectInputChannel, val owner: String) {
        @Volatile var ready = false
        @Volatile var retiring = false
        @Volatile var keyboardRequested = false
        @Volatile var keyboardEnabled = false
        val keyboardChanging = java.util.concurrent.atomic.AtomicBoolean(false)
        var keyboardState: RemoteKeyboardAdapter.State? = null
        var keyboardResult = RemoteKeyboardAdapter.Result.ACCEPTED
    }
    private val grants = ConcurrentHashMap<String, DirectInputChannel>()
    private val participants = ConcurrentHashMap<String, Participant>()
    private val admission = Any()
    private val mailbox = SharedInputMailbox()
    private val wake = Channel<Unit>(Channel.CONFLATED)
    @Volatile private var resetRequired = false
    @Volatile private var groupRetiring = false
    private var pipe: TouchPipe? = null
    private var arbiter: SharedPointerArbiter? = null
    private var binding: TouchBinding? = null
    private var nativeSequence = 0
    private var nativeAt = 0L
    private var nativeX = 0
    private var nativeY = 0
    private var lastNativeAt = 0L
    private var keyboardStateAt = 0L

    init {
        scope.launch(dispatcher) {
            try {
                while (isActive) {
                    if (participants.isEmpty()) wake.receive() else withTimeoutOrNull(10) { wake.receive() }
                    if (participants.isEmpty()) continue
                    try { drain() } catch (failure: kotlinx.coroutines.CancellationException) { throw failure }
                    catch (failure: Exception) {
                        diagnostics.inputFailed(failure.message ?: "native_adapter_exception")
                        retireGroup()
                    }
                }
            } finally {
                withContext(NonCancellable) { retireGroup(); keyboard?.reset() }
                grants.clear(); wake.close()
            }
        }
    }

    fun owns(session: String): Boolean = grants.containsKey(session)

    fun grant(channel: DirectInputChannel): Boolean = synchronized(admission) {
        // Granting this authenticated transport does not acquire native input.
        // An unavailable injector must not tear down a healthy video peer.
        if (!channel.isCurrent() || channel.capture != capture()) return false
        val prior = grants[channel.session]
        if (prior != null) return prior.isCurrent() && prior.capture == channel.capture
        if (grants.size >= SharedPointerArbiter.MAX_PARTICIPANTS) return false
        grants[channel.session] = channel
        true
    }

    fun message(session: String, message: JsonObject): Boolean {
        val channel = grants[session] ?: return false
        if (!current(channel)) { closed(session); return false }
        val type = (message["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (type == "touch_open") return open(channel, message)
        val participant = participants[session] ?: return false
        if (type == "touch_close" && message.keys == setOf("type")) {
            retire(participant); return true
        }
        if (type == "keyboard_mode" && message.keys == setOf("type", "enabled") && message["enabled"] in setOf(JsonPrimitive(true), JsonPrimitive(false))) {
            if (!channel.keyboardSupported || keyboard == null || !participant.ready || participant.retiring) return false
            val requested = message["enabled"] == JsonPrimitive(true)
            if (requested == participant.keyboardRequested) { keyboardState(participant, "current"); return true }
            val start = synchronized(admission) {
                participant.keyboardRequested = requested
                participant.keyboardChanging.compareAndSet(false, true)
            }
            if (!start) return true
            scope.launch(Dispatchers.IO) {
                var completed = false
                try {
                    while (isActive && !participant.retiring && current(channel)) {
                        val desired = participant.keyboardRequested
                        if (desired) {
                            val enabled = runCatching { keyboard.enable(participant.owner) }.getOrDefault(false)
                            participant.keyboardEnabled = enabled && participant.keyboardRequested && !participant.retiring && current(channel)
                            if (!participant.keyboardEnabled) keyboard.disable(participant.owner)
                            keyboardState(participant, if (participant.keyboardEnabled) "ready" else "unavailable")
                        } else {
                            keyboard.release(participant.owner)
                            participant.keyboardEnabled = false
                            keyboard.disable(participant.owner)
                            keyboardState(participant, "disabled")
                        }
                        completed = synchronized(admission) {
                            if (desired == participant.keyboardRequested) { participant.keyboardChanging.set(false); true } else false
                        }
                        if (completed) break
                    }
                } finally {
                    if (!completed) participant.keyboardChanging.set(false)
                    if (participant.retiring || !current(channel) || !participant.keyboardRequested) {
                        participant.keyboardEnabled = false
                        keyboard.disable(participant.owner)
                        keyboardState(participant, "disabled")
                    }
                }
            }
            return true
        }
        val keyboardCommand = if (type == "keyboard_event") RemoteKeyboardCommand.parse(message) else null
        if (type == "keyboard_event" && (keyboardCommand == null || !channel.keyboardSupported || keyboard == null || !participant.keyboardEnabled)) {
            retire(participant); return true
        }
        val key = type == "key_event" && message.keys == setOf("type", "sequence", "keycode")
        if (!key && keyboardCommand == null && (type != "touch_event" || message.keys != setOf("type", "sequence", "gesture", "action", "x", "y"))) {
            retire(participant); return false
        }
        val sequence = integer(message, "sequence")
        val gesture = if (key || keyboardCommand != null) 0L else number(message, "gesture")
        val action = if (keyboardCommand != null) RemoteKeyboardCommand.ACTION else if (key) RootTouchSession.KEY_TAP else integer(message, "action")
        val keyCode = if (key) integer(message, "keycode") else null
        val x = integer(message, "x"); val y = integer(message, "y")
        val mapped = if (x != null && y != null) channel.capture.map(channel.capture.epoch,
            channel.capture.frameWidth, channel.capture.frameHeight, StreamPoint(x, y)) else null
        if (sequence == null || gesture == null || action == null
            || (if (keyboardCommand != null) false else if (key) keyCode == null || !RootTouchSession.supportedKey(keyCode) else mapped == null) || participant.retiring
            || !participant.ready && action != RootTouchSession.HEARTBEAT) {
            retire(participant); return true
        }
        val event = SharedPointerArbiter.Event(participant.owner, sequence, gesture, action,
            if (keyboardCommand != null) 0 else if (key) checkNotNull(keyCode) else checkNotNull(mapped).x,
            if (key || keyboardCommand != null) 0 else checkNotNull(mapped).y, uptime(), keyboardCommand)
        if (mailbox.offer(event) !in setOf(SharedInputMailbox.Admission.QUEUED, SharedInputMailbox.Admission.COALESCED)) {
            retire(participant)
        }
        wake.trySend(Unit)
        return true
    }

    fun closed(session: String) {
        grants.remove(session)
        participants[session]?.let { retire(it) }
    }

    fun invalidate() {
        grants.clear()
        participants.values.forEach { retire(it) }
    }

    fun diagnosticSnapshot(): JsonObject? = if (participants.isEmpty() && !resetRequired) null else
        diagnostics.snapshot(when {
            resetRequired -> NativeInputDiagnostics.State.CLEANUP_UNKNOWN
            groupRetiring -> NativeInputDiagnostics.State.RETIRING
            participants.values.any { it.ready && !it.retiring } -> NativeInputDiagnostics.State.READY
            else -> NativeInputDiagnostics.State.OPENING
        })

    private fun current(channel: DirectInputChannel): Boolean =
        grants[channel.session] === channel && channel.isCurrent() && channel.capture == capture()

    private fun open(channel: DirectInputChannel, message: JsonObject): Boolean = synchronized(admission) {
        if (message.keys != setOf("type", "capture_epoch", "frame_width", "frame_height")
            || message["capture_epoch"] != JsonPrimitive(channel.capture.epoch)
            || integer(message, "frame_width") != channel.capture.frameWidth
            || integer(message, "frame_height") != channel.capture.frameHeight || !current(channel)
            || participants.containsKey(channel.session) || participants.size >= SharedPointerArbiter.MAX_PARTICIPANTS) return false
        val participant = Participant(channel, UUID.randomUUID().toString().replace("-", ""))
        diagnostics.record(NativeInputDiagnostics.Event.OPEN_ATTEMPT)
        if (!mailbox.register(participant.owner)) return false
        participants[channel.session] = participant
        if (!send(participant, buildJsonObject {
            put("type", "touch_session"); put("session_id", channel.session); put("owner", participant.owner)
            put("capture_epoch", channel.capture.epoch); put("frame_width", channel.capture.frameWidth)
            put("frame_height", channel.capture.frameHeight)
        })) retire(participant)
        if (resetRequired || groupRetiring) {
            status(participant, 0, 0, 4, "denied")
            remove(participant)
            status(participant, 0, 0, 3, "closed")
            return true
        }
        wake.trySend(Unit)
        true
    }

    private fun retire(participant: Participant) {
        participant.retiring = true
        mailbox.retire(participant.owner)
        wake.trySend(Unit)
    }

    private suspend fun drain() {
        for (participant in participants.values) if (!current(participant.channel)) retire(participant)
        val candidate = participants.values.firstOrNull { !it.retiring }
        if (pipe == null && candidate != null) {
            if (resetRequired) {
                participants.values.forEach { status(it, 0, 0, 4, "unknown"); retire(it) }
            } else {
                val cap = candidate.channel.capture
                val owner = "shared_" + UUID.randomUUID().toString().replace("-", "")
                val nextBinding = TouchBinding(owner, cap.epoch, cap.physicalWidth, cap.physicalHeight, cap.rotation)
                val nextPipe = try { factory.open(nextBinding) } catch (failure: Exception) {
                    if (failure is TouchPipeCleanupUnknownException || failure is kotlinx.coroutines.CancellationException) {
                        resetRequired = true
                        throw failure
                    }
                    // A refusal before native READY has no applied touch to replay.
                    diagnostics.record(NativeInputDiagnostics.Event.OPEN_REJECTION, NativeInputDiagnostics.Failure.NATIVE_STARTUP_FAILED)
                    participants.values.toList().forEach {
                        status(it, 0, 0, 4, "denied"); remove(it); status(it, 0, 0, 3, "closed")
                    }
                    return
                }
                binding = nextBinding; pipe = nextPipe; nativeSequence = 0
                diagnostics.record(NativeInputDiagnostics.Event.STARTUP)
                lastNativeAt = uptime()
                arbiter = SharedPointerArbiter(cap.physicalWidth, cap.physicalHeight, uptime) { action ->
                    if (action.action == RemoteKeyboardCommand.ACTION) {
                        val p = participants.values.firstOrNull { it.owner == action.participant }
                        if (p == null || !p.keyboardEnabled || !current(p.channel)) false else {
                            p.keyboardResult = runCatching { checkNotNull(keyboard).apply(p.owner, checkNotNull(action.keyboard)) {
                                !p.retiring && p.keyboardEnabled && current(p.channel)
                            } }
                                .getOrDefault(RemoteKeyboardAdapter.Result.UNKNOWN)
                            nativeAt = uptime()
                            true // Text refusal/uncertainty is reported explicitly, without killing healthy pointer peers.
                        }
                    } else {
                    val ack = nextPipe.send(TouchSample(++nativeSequence, action.gesture, action.action, action.x, action.y, uptime()))
                    if (action.action == RootTouchSession.KEY_RESET && action.participant != null) keyboard?.release(action.participant)
                    nativeAt = ack.uptimeMs; lastNativeAt = uptime()
                    if (action.action <= RootTouchSession.HEARTBEAT) { nativeX = action.x; nativeY = action.y }
                    if (ack.status >= 4) diagnostics.inputFailed(when (ack.status) {
                        4 -> "native_expired"; 5 -> "native_rejected"; else -> "native_unknown"
                    })
                    ack.sequence == nativeSequence && ack.status == (if (action.action == RootTouchSession.CANCEL) 3 else 1)
                    }
                }
            }
        }
        val currentArbiter = arbiter
        if (currentArbiter != null) {
            for (participant in participants.values) {
                if (participant.ready || participant.retiring) continue
                if (!current(participant.channel) || binding?.captureEpoch != participant.channel.capture.epoch) {
                    retire(participant); continue
                }
                if (!currentArbiter.attach(participant.owner, uptime() + SharedPointerArbiter.MAX_GRANT_MS, true)) {
                    status(participant, 0, 0, 4, "denied"); remove(participant); continue
                }
                participant.ready = true
                status(participant, 0, 0, 4, "ready")
            }
        }
        // A finite pass prevents a fast mouse from starving expiry/native heartbeat.
        repeat(SharedPointerArbiter.MAX_PARTICIPANTS * SharedInputMailbox.PER_PARTICIPANT) {
            when (val work = mailbox.poll() ?: return@repeat) {
                is SharedInputMailbox.Work.Close -> {
                    val p = participants.values.firstOrNull { it.owner == work.participant } ?: return@repeat
                    val notices = currentArbiter?.remove(p.owner).orEmpty()
                    currentArbiter?.takeKeyboardInterruption()?.takeIf { it.participant != p.owner }?.let { notice(it,null) }
                    if (currentArbiter?.fenced == true) { retireGroup(); return }
                    notices.filter { it.participant != p.owner }.forEach { notice(it, null) }
                    remove(p); status(p, 0, 0, 3, "closed"); diagnostics.record(NativeInputDiagnostics.Event.RELEASE)
                }
                is SharedInputMailbox.Work.Input -> {
                    val p = participants.values.firstOrNull { it.owner == work.event.participant } ?: return@repeat
                    if (!p.ready || p.retiring || !current(p.channel)) { retire(p); return@repeat }
                    p.keyboardResult = RemoteKeyboardAdapter.Result.ACCEPTED
                    val notices = currentArbiter?.offer(work.event).orEmpty()
                    if (currentArbiter?.fenced == true) { retireGroup(); return }
                    currentArbiter?.takeKeyboardInterruption()?.let { notice(it,null) }
                    notices.forEach { notice(it, work.event) }
                }
            }
        }
        currentArbiter?.expire()?.forEach { notice(it, null) }
        if (currentArbiter?.fenced == true) { retireGroup(); return }
        if (participants.isEmpty()) { closePipe(); return }
        val now = uptime()
        if (keyboard != null && participants.values.any { it.keyboardEnabled } && now - keyboardStateAt >= 250) {
            if (keyboard is AndroidRemoteKeyboard) keyboard.refresh()
            keyboardStateAt = now
            participants.values.filter { it.keyboardEnabled }.forEach { if (it.keyboardState != keyboard.state()) keyboardState(it, "current") }
        }
        if (pipe != null && now - lastNativeAt >= 250) {
            val ack = checkNotNull(pipe).send(TouchSample(++nativeSequence, currentArbiter?.nativeHeldGesture ?: 0,
                RootTouchSession.HEARTBEAT, nativeX, nativeY, now))
            check(ack.status == 2 && ack.sequence == nativeSequence)
            nativeAt = ack.uptimeMs; lastNativeAt = uptime()
        }
    }

    private fun notice(notice: SharedPointerArbiter.Notice, event: SharedPointerArbiter.Event?) {
        val participant = participants.values.firstOrNull { it.owner == notice.participant } ?: return
        val action = if (event?.participant == participant.owner) event.action else 4
        if (action == RemoteKeyboardCommand.ACTION && notice.outcome in setOf(SharedPointerArbiter.Outcome.APPLIED, SharedPointerArbiter.Outcome.INTERRUPTED)) {
            if (notice.outcome == SharedPointerArbiter.Outcome.APPLIED) diagnostics.keyboard(participant.keyboardResult)
            send(participant, buildJsonObject {
                put("type", "keyboard_result"); put("session_id", participant.channel.session); put("owner", participant.owner)
                put("capture_epoch", participant.channel.capture.epoch); put("sequence", notice.sequence)
                put("outcome", if (notice.outcome == SharedPointerArbiter.Outcome.INTERRUPTED) "interrupted" else participant.keyboardResult.name.lowercase())
                put("device_uptime_ms", nativeAt)
            })
            return
        }
        status(participant, notice.sequence, notice.gesture, action, notice.outcome.name.lowercase())
        if (notice.outcome in setOf(SharedPointerArbiter.Outcome.CLOSED, SharedPointerArbiter.Outcome.DENIED,
                SharedPointerArbiter.Outcome.EXPIRED, SharedPointerArbiter.Outcome.INVALID)) {
            status(participant, 0, 0, 3, "closed")
            remove(participant)
        }
    }

    private fun status(participant: Participant, sequence: Int, gesture: Long, action: Int, outcome: String) {
        if (!send(participant, buildJsonObject {
            put("type", "shared_input_status"); put("session_id", participant.channel.session)
            put("owner", participant.owner); put("capture_epoch", participant.channel.capture.epoch)
            put("sequence", sequence); put("gesture", gesture); put("action", action); put("outcome", outcome)
            put("device_uptime_ms", if (outcome == "applied") nativeAt else uptime())
        })) retire(participant)
    }

    private fun send(participant: Participant, message: JsonObject): Boolean =
        runCatching { participant.channel.isCurrent() && participant.channel.send(message) }.getOrDefault(false)

    private fun remove(participant: Participant) = synchronized(admission) {
        participant.retiring = true
        participants.remove(participant.channel.session, participant)
        mailbox.remove(participant.owner)
        if (participant.keyboardRequested || participant.keyboardEnabled) {
            participant.keyboardRequested = false; participant.keyboardEnabled = false
            scope.launch(Dispatchers.IO) {
                keyboard?.release(participant.owner)
                keyboard?.disable(participant.owner)
            }
        }
    }

    private fun keyboardState(participant: Participant, reason: String) {
        val state = keyboard?.state() ?: RemoteKeyboardAdapter.State(false, 0, false)
        participant.keyboardState = state
        if (!participant.retiring) send(participant, buildJsonObject {
            put("type", "keyboard_state"); put("session_id", participant.channel.session); put("owner", participant.owner)
            put("capture_epoch", participant.channel.capture.epoch); put("enabled", participant.keyboardEnabled)
            put("editor_generation", state.editorGeneration); put("editor_active", participant.keyboardEnabled && state.editorActive)
            put("reason", reason)
        })
    }

    private suspend fun closePipe(): Boolean {
        val old = pipe; pipe = null; arbiter = null; binding = null
        val confirmed = old == null || runCatching { old.closeAndConfirm() }.getOrDefault(false)
        if (!confirmed) resetRequired = true // Preserve the original native failure discriminator.
        return confirmed
    }

    private suspend fun retireGroup() {
        val pending = synchronized(admission) { groupRetiring = true; participants.values.toList() }
        if (pending.isNotEmpty()) diagnostics.record(NativeInputDiagnostics.Event.INPUT_FAILURE, NativeInputDiagnostics.Failure.NATIVE_INPUT_FAILED)
        pending.forEach { status(it, 0, 0, 4, "unknown") }
        val confirmed = closePipe()
        pending.forEach { remove(it) }
        mailbox.clear()
        if (!confirmed) diagnostics.record(NativeInputDiagnostics.Event.UNKNOWN_RELEASE, NativeInputDiagnostics.Failure.CLEANUP_UNKNOWN)
        groupRetiring = false
        pending.forEach { if (confirmed) status(it, 0, 0, 3, "closed") }
    }

    private fun integer(value: JsonObject, key: String): Int? = (value[key] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
    private fun number(value: JsonObject, key: String): Long? = (value[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
}
