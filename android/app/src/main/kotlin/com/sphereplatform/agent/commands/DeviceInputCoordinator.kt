package com.sphereplatform.agent.commands

import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext

internal class InputAutomationCleanupUnknownException : IllegalStateException("input_automation_cleanup_unknown")

/** Reserve admission first, drain both native routes, then allow exactly one task reservation. */
internal class DeviceInputCoordinator(
    private val ownership: DeviceInputOwnership,
    private val releaseShared: suspend (String) -> AutoCloseable,
    private val releaseFallback: suspend () -> Boolean,
    private val onUnknown: () -> Unit = {},
) {
    suspend fun acquire(taskId: String): AutoCloseable {
        val pause = ownership.pauseContinuous()
        var shared: AutoCloseable? = null
        try {
            shared = releaseShared(taskId)
            val known = withContext(NonCancellable) { releaseFallback() }
            if (!known) {
                ownership.fence()
                throw InputAutomationCleanupUnknownException()
            }
            currentCoroutineContext().ensureActive()
            val held = shared
            return AutoCloseable { try { pause.close() } finally { held.close() } }
        } catch (failure: Throwable) {
            if (failure is InputAutomationCleanupUnknownException) { ownership.fence(); onUnknown() }
            // Draining is awaited by each adapter even on cancellation. Clearing
            // this admission pause cannot clear an uncertain native ownership fence.
            try { pause.close() } finally { shared?.close() }
            throw failure
        }
    }
}
