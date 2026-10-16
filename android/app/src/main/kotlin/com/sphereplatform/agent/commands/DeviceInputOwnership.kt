package com.sphereplatform.agent.commands

import kotlinx.coroutines.asContextElement
import kotlin.coroutines.CoroutineContext

class DeviceInputBusyException : IllegalStateException("device_input_busy")

/** Only the task's structured coroutine tree may use its nested primitives. */
class TaskInputReservation internal constructor(val context: CoroutineContext, private val release: () -> Unit) : AutoCloseable {
    override fun close() = release()
}

/** Shared by all AdbActionExecutor mutations, complete DAG execution and the continuous helper. */
internal class DeviceInputOwnership {
    private var discrete = 0
    private var owner: String? = null
    private var uncertain = false
    private var manualPauses = 0
    private var task: Any? = null
    private val taskContext = ThreadLocal<Any?>()

    @Synchronized
    fun claimDiscrete(): AutoCloseable {
        if (owner != null || uncertain || task != null && taskContext.get() !== task) throw DeviceInputBusyException()
        discrete++
        return object : AutoCloseable {
            private var closed = false
            override fun close() = synchronized(this@DeviceInputOwnership) {
                if (!closed) { closed = true; discrete-- }
            }
        }
    }

    @Synchronized
    fun claimContinuous(candidate: String): Boolean {
        require(candidate.matches(Regex("[A-Za-z0-9_-]{8,128}")))
        if (owner != null || discrete != 0 || uncertain || manualPauses != 0 || task != null) return false
        owner = candidate
        return true
    }

    @Synchronized fun owns(candidate: String): Boolean = owner == candidate && !uncertain

    /** Fence new helpers before asking existing owners to release. Does not revoke their cleanup authority. */
    @Synchronized fun pauseContinuous(): AutoCloseable {
        manualPauses++
        var closed = false
        return AutoCloseable { synchronized(this) { if (!closed) { closed = true; manualPauses-- } } }
    }

    @Synchronized fun claimTask(): TaskInputReservation {
        if (owner != null || uncertain || discrete != 0 || task != null) throw DeviceInputBusyException()
        val token = Any(); task = token
        var closed = false
        return TaskInputReservation(taskContext.asContextElement(token)) {
            synchronized(this) {
                if (!closed) {
                    closed = true
                    if (discrete != 0) uncertain = true
                    if (task === token) task = null
                }
            }
        }
    }

    @Synchronized fun fence() { uncertain = true }

    @Synchronized
    fun release(candidate: String, confirmed: Boolean) {
        if (owner != candidate) return
        if (!confirmed) uncertain = true
        // Unknown release retains the fence. There is intentionally no automatic reset.
        if (confirmed && !uncertain) owner = null
    }
}
