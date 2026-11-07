package com.sphereplatform.agent.commands

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class DeviceInputCoordinatorTest {
    @Test fun `task waits for both native adapters and admission returns only after its lease closes`() = runBlocking<Unit> {
        val ownership = DeviceInputOwnership(); val order = mutableListOf<String>()
        assertTrue(ownership.claimContinuous("manual_owner_1234"))
        val coordinator = DeviceInputCoordinator(ownership, {
            assertFalse(ownership.claimContinuous("racing_owner_5678"))
            order += "shared"; ownership.release("manual_owner_1234", true)
            AutoCloseable { order += "resume" }
        }, { order += "fallback"; true })
        val gate = coordinator.acquire("task_automation_1234")
        val task = ownership.claimTask()
        assertEquals(listOf("shared", "fallback"), order)
        assertFalse(ownership.claimContinuous("racing_owner_5678"))
        task.close(); gate.close()
        assertEquals(listOf("shared", "fallback", "resume"), order)
        assertTrue(ownership.claimContinuous("racing_owner_5678"))
    }

    @Test fun `unknown fallback cleanup keeps a global input fence after every lease is released`() = runBlocking<Unit> {
        val ownership = DeviceInputOwnership(); var unknown = 0; var released = 0
        val coordinator = DeviceInputCoordinator(ownership, { AutoCloseable { released++ } }, { false }, { unknown++ })
        assertTrue(runCatching { coordinator.acquire("task_automation_1234") }.exceptionOrNull() is InputAutomationCleanupUnknownException)
        assertEquals(1, released); assertEquals(1, unknown)
        assertFalse(ownership.claimContinuous("manual_owner_1234"))
        assertThrows(DeviceInputBusyException::class.java) { ownership.claimTask() }
    }

    @Test fun `cancelled preparation finishes bounded native cleanup before exposing manual admission`() = runBlocking<Unit> {
        val ownership = DeviceInputOwnership(); val entered = CompletableDeferred<Unit>(); val finish = CompletableDeferred<Unit>()
        var resumed = false
        val coordinator = DeviceInputCoordinator(ownership, { AutoCloseable { resumed = true } }, { entered.complete(Unit); finish.await(); true })
        val job = async { coordinator.acquire("task_automation_1234") }
        entered.await(); job.cancel()
        assertFalse(resumed); assertFalse(ownership.claimContinuous("manual_owner_1234"))
        finish.complete(Unit); job.join()
        assertTrue(resumed); assertTrue(ownership.claimContinuous("manual_owner_1234"))
    }
}
