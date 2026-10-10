package com.sphereplatform.agent.commands

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class DeviceInputOwnershipTest {
    @Test fun `complete DAG reservation excludes continuous input including between nested actions`() {
        val ownership = DeviceInputOwnership()
        val dag = ownership.claimDiscrete()
        ownership.claimDiscrete().close()
        assertFalse(ownership.claimContinuous("owner_1234"))
        dag.close(); dag.close()
        assertTrue(ownership.claimContinuous("owner_1234"))
        assertThrows(DeviceInputBusyException::class.java) { ownership.claimDiscrete() }
    }

    @Test fun `foreign owner cannot release or poison the legitimate owner`() {
        val ownership = DeviceInputOwnership()
        assertTrue(ownership.claimContinuous("owner_1234"))
        ownership.release("foreign_5678", false)
        ownership.release("foreign_5678", true)
        assertTrue(ownership.owns("owner_1234"))
        assertFalse(ownership.claimContinuous("foreign_5678"))
        ownership.release("owner_1234", true)
        ownership.claimDiscrete().close()
    }

    @Test fun `unknown cleanup cannot be cleared by a subsequent optimistic release`() {
        val ownership = DeviceInputOwnership()
        ownership.claimContinuous("owner_1234")
        ownership.release("owner_1234", false)
        ownership.release("owner_1234", true)
        assertFalse(ownership.owns("owner_1234"))
        assertFalse(ownership.claimContinuous("another_5678"))
        assertThrows(DeviceInputBusyException::class.java) { ownership.claimDiscrete() }
    }

    @Test fun `reservation precedes FIFO handoff and prevents concurrent primitives`() = runBlocking {
        val ownership = DeviceInputOwnership()
        val entered = CompletableDeferred<Unit>(); val release = CompletableDeferred<Unit>()
        var opened = 0
        val factory = OwnedTouchPipeFactory(ownership, { entered.complete(Unit); release.await() }, TouchPipeFactory {
            opened++; testPipe(true)
        })
        val opening = async { factory.open(binding()) }
        entered.await()
        assertEquals(0, opened)
        assertThrows(DeviceInputBusyException::class.java) { ownership.claimDiscrete() }
        release.complete(Unit)
        val pipe = opening.await()
        assertEquals(1, opened)
        assertTrue(pipe.closeAndConfirm())
        ownership.claimDiscrete().close()
    }

    @Test fun `busy DAG never starts a root helper`() = runBlocking {
        val ownership = DeviceInputOwnership()
        val dag = ownership.claimDiscrete()
        var touched = false
        val factory = OwnedTouchPipeFactory(ownership, { touched = true }, TouchPipeFactory { touched = true; testPipe(true) })
        assertFails { factory.open(binding()) }
        assertFalse(touched)
        dag.close()
    }

    @Test fun `uncertain FIFO handoff never starts or silently releases the injector fence`() = runBlocking<Unit> {
        val ownership = DeviceInputOwnership()
        var opened = false
        val factory = OwnedTouchPipeFactory(ownership, { throw RootCommandOutcomeUnknownException() }, TouchPipeFactory {
            opened = true; testPipe(true)
        })
        assertFails { factory.open(binding()) }
        assertFalse(opened)
        assertFalse(ownership.claimContinuous("another_5678"))
        assertThrows(DeviceInputBusyException::class.java) { ownership.claimDiscrete() }
    }

    @Test fun `known startup failure releases reservation but unknown helper cleanup keeps it`() = runBlocking {
        for (unknown in listOf(false, true)) {
            val ownership = DeviceInputOwnership()
            val factory = OwnedTouchPipeFactory(ownership, {}, TouchPipeFactory {
                if (unknown) throw TouchPipeCleanupUnknownException() else throw java.io.IOException("startup_rejected")
            })
            assertFails { factory.open(binding()) }
            assertEquals(!unknown, ownership.claimContinuous("another_5678"))
        }
    }

    @Test fun `unknown close or thrown cleanup retains ownership and close is attempted once`() = runBlocking {
        for (throws in listOf(false, true)) {
            val ownership = DeviceInputOwnership()
            var closes = 0
            val pipe = OwnedTouchPipeFactory(ownership, {}, TouchPipeFactory {
                object : TouchPipe {
                    override suspend fun send(sample: TouchSample) = ack(sample.sequence)
                    override suspend fun closeAndConfirm(): Boolean { closes++; if (throws) throw java.io.IOException(); return false }
                }
            }).open(binding())
            runCatching { pipe.closeAndConfirm() }
            assertFalse(pipe.closeAndConfirm())
            assertEquals(1, closes)
            assertThrows(DeviceInputBusyException::class.java) { ownership.claimDiscrete() }
        }
    }

    private fun binding() = TouchBinding("owner_1234", "epoch_1234", 960, 540, 0)
    private fun testPipe(confirmed: Boolean) = object : TouchPipe {
        override suspend fun send(sample: TouchSample) = ack(sample.sequence)
        override suspend fun closeAndConfirm() = confirmed
    }
    private suspend fun assertFails(block: suspend () -> Any?) {
        try { block(); fail("Expected startup rejection") } catch (_: java.io.IOException) {}
    }
    private fun ack(sequence: Int) = java.io.ByteArrayOutputStream().let {
        RootTouchWire.ack(it, sequence, 1, 1)
        RootTouchWire.readAck(java.io.ByteArrayInputStream(it.toByteArray()))
    }
}
