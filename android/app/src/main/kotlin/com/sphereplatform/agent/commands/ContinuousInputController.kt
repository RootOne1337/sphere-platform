package com.sphereplatform.agent.commands

import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.StreamPoint
import com.sphereplatform.agent.streaming.StreamingManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Canary admission from the authenticated server socket, never directly from a browser or Intent. */
internal class ContinuousInputController(
    private val scope: CoroutineScope,
    factory: TouchPipeFactory,
    private val streaming: StreamingManager,
    private val generation: () -> Long?,
    private val send: (Long, JsonObject) -> Boolean,
    private val uptime: () -> Long,
    private val enabled: Boolean,
) {
    private data class Owner(val binding: TouchBinding, val session: String, val generation: Long, val capture: CaptureInputSession) {
        @Volatile var retired = false
        @Volatile var admitted = false
        @Volatile var ready = false
    }
    private val active = AtomicReference<Owner?>()
    private val closing = AtomicBoolean(false)
    private val supervisor = ContinuousTouchSupervisor(scope, factory, uptime,
        isCurrent = { binding ->
            val owner = active.get()
            owner?.binding == binding && current(owner)
        },
        onReceipt = { binding, receipt ->
            val owner = active.get()
            if (owner?.binding == binding) {
                val ready = receipt.stage == ContinuousTouchSupervisor.Stage.STARTUP && receipt.status == 0
                val staleReady = ready && !current(owner)
                if (ready && !staleReady) owner.ready = true
                if (staleReady || !reply(owner, receipt.sequence, receipt.status, receipt.stage.name.lowercase(), "injector", receipt.deviceUptimeMs)) {
                    supervisorInvalidation()
                }
                if (receipt.stage == ContinuousTouchSupervisor.Stage.RELEASE) active.compareAndSet(owner, null)
            }
        },
    )

    /** Called synchronously before CommandDispatcher creates coroutines for ordinary commands. */
    fun handle(message: JsonObject): Boolean {
        val type = (message["type"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
        if (type !in setOf("continuous_input_probe", "continuous_input_open", "continuous_input_event", "continuous_input_close")) return false
        if (!enabled) return true // Default/release builds expose no experimental capability.
        val connection = generation() ?: return true
        when (type) {
            "continuous_input_probe" -> probe(message, connection)
            "continuous_input_open" -> open(message, connection)
            "continuous_input_event" -> offer(message, connection)
            "continuous_input_close" -> {
                val owner = active.get()
                if (owner != null && owner.generation == connection && identifier(message, "owner") == owner.binding.owner) invalidate()
            }
        }
        return true
    }

    /** Local lifecycle loss is immediate fencing; teardown runs outside capture/socket locks. */
    fun invalidate() {
        if (!enabled) return
        active.get()?.retired = true
        supervisorInvalidation()
        if (closing.compareAndSet(false, true)) scope.launch {
            try { supervisor.close() } finally { closing.set(false) }
        }
    }

    private fun supervisorInvalidation() { supervisor.invalidate() }

    private fun probe(message: JsonObject, connection: Long) {
        val session = identifier(message, "session_id") ?: return
        if (!exact(message, setOf("type", "session_id"))) return
        val capture = capture() ?: return
        runCatching { send(connection, buildJsonObject {
            put("type", "continuous_input_offer"); put("session_id", session)
            put("protocol_version", 1); put("injector_ready", false)
            put("frame_protocol_version", 2)
            put("display_id", 0); put("max_pointers", 1)
            put("capture_epoch", capture.epoch)
            put("frame_width", capture.frameWidth); put("frame_height", capture.frameHeight)
            put("physical_width", capture.physicalWidth); put("physical_height", capture.physicalHeight)
            put("rotation", capture.rotation)
        }) }
    }

    private fun open(message: JsonObject, connection: Long) {
        val ownerId = identifier(message, "owner") ?: return
        val session = identifier(message, "session_id") ?: return
        val epoch = identifier(message, "capture_epoch") ?: return
        val width = integer(message, "frame_width") ?: return
        val height = integer(message, "frame_height") ?: return
        if (!exact(message, setOf("type", "owner", "session_id", "capture_epoch", "frame_width", "frame_height"))) return
        val capture = capture() ?: return
        if (capture.epoch != epoch || capture.frameWidth != width || capture.frameHeight != height) return
        val candidate = Owner(TouchBinding(ownerId, epoch, capture.physicalWidth, capture.physicalHeight, capture.rotation), session, connection, capture)
        if (closing.get() || !active.compareAndSet(null, candidate)) {
            reply(candidate, 0, 5, "startup", "admission", uptime())
            return
        }
        // Only one lifecycle coroutine can be admitted. MOVE messages never allocate a coroutine.
        scope.launch {
            if (!current(candidate) || !supervisor.open(candidate.binding)) {
                active.compareAndSet(candidate, null)
                reply(candidate, 0, 5, "startup", "admission", uptime())
            } else candidate.admitted = true
        }.invokeOnCompletion {
            // A scope cancelled before the block started cannot leave an orphan reservation.
            if (!candidate.admitted) active.compareAndSet(candidate, null)
        }
    }

    private fun offer(message: JsonObject, connection: Long) {
        val owner = active.get() ?: return
        if (owner.generation != connection || identifier(message, "owner") != owner.binding.owner) return
        val epoch = identifier(message, "capture_epoch")
        val sequence = integer(message, "sequence")
        val gesture = number(message, "gesture")
        val action = integer(message, "action")
        val x = integer(message, "x"); val y = integer(message, "y")
        val valid = exact(message, setOf("type", "owner", "capture_epoch", "sequence", "gesture", "action", "x", "y"))
            && epoch != null && sequence != null && gesture != null && action != null && x != null && y != null
        val point = if (valid && current(owner)) owner.capture.map(epoch!!, owner.capture.frameWidth, owner.capture.frameHeight, StreamPoint(x!!, y!!)) else null
        if (point == null) {
            reply(owner, sequence?.coerceAtLeast(0) ?: 0, 5, "input", "admission", uptime())
            invalidate()
            return
        }
        if (!owner.ready && action != RootTouchSession.HEARTBEAT) {
            reply(owner, sequence!!.coerceAtLeast(0), 5, "input", "admission", uptime())
            invalidate()
            return
        }
        if (!owner.admitted && action == RootTouchSession.HEARTBEAT) return
        val result = supervisor.offer(owner.binding.owner, epoch!!, sequence!!, gesture!!, action!!, point.x, point.y)
        if (result !in setOf(ContinuousTouchMailbox.Admission.QUEUED, ContinuousTouchMailbox.Admission.COALESCED)) {
            reply(owner, sequence.coerceAtLeast(0), 5, "input", "admission", uptime())
            invalidate()
        }
    }

    private fun current(owner: Owner): Boolean = scope.isActive && !owner.retired && active.get() === owner &&
        generation() == owner.generation && capture() == owner.capture

    private fun capture(): CaptureInputSession? = runCatching { streaming.getInputSession() }.getOrNull()

    private fun reply(owner: Owner, sequence: Int, status: Int, stage: String, origin: String, now: Long): Boolean = runCatching { send(owner.generation, buildJsonObject {
        put("type", "continuous_input_status"); put("session_id", owner.session)
        put("owner", owner.binding.owner); put("capture_epoch", owner.binding.captureEpoch)
        put("sequence", sequence); put("status", status); put("stage", stage); put("origin", origin)
        put("device_uptime_ms", now)
    }) }.getOrDefault(false)

    private fun identifier(message: JsonObject, key: String): String? = (message[key] as? JsonPrimitive)
        ?.takeIf { it.isString }?.contentOrNull?.takeIf { it.matches(Regex("[A-Za-z0-9_-]{8,128}")) }
    private fun number(message: JsonObject, key: String): Long? = (message[key] as? JsonPrimitive)
        ?.takeIf { !it.isString }?.longOrNull
    private fun integer(message: JsonObject, key: String): Int? = (message[key] as? JsonPrimitive)
        ?.takeIf { !it.isString }?.intOrNull
    private fun exact(message: JsonObject, keys: Set<String>): Boolean = message.keys == keys
}
