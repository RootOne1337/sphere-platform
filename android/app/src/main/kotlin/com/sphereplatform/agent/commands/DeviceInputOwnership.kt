package com.sphereplatform.agent.commands

class DeviceInputBusyException : IllegalStateException("device_input_busy")

/** Shared by all AdbActionExecutor mutations, complete DAG execution and the continuous helper. */
internal class DeviceInputOwnership {
    private var discrete = 0
    private var owner: String? = null
    private var uncertain = false

    @Synchronized
    fun claimDiscrete(): AutoCloseable {
        if (owner != null || uncertain) throw DeviceInputBusyException()
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
        if (owner != null || discrete != 0 || uncertain) return false
        owner = candidate
        return true
    }

    @Synchronized fun owns(candidate: String): Boolean = owner == candidate && !uncertain

    @Synchronized
    fun release(candidate: String, confirmed: Boolean) {
        if (owner != candidate) return
        if (!confirmed) uncertain = true
        // Unknown release retains the fence. There is intentionally no automatic reset.
        if (confirmed && !uncertain) owner = null
    }
}
