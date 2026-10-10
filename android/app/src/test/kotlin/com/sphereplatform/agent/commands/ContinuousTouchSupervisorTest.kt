package com.sphereplatform.agent.commands

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicLong

class ContinuousTouchSupervisorTest {
    private val binding = TouchBinding("owner_012345", "capture_012345",960,540,0)
    private fun ack(sequence: Int, status: Int) = ByteArrayOutputStream().let {
        RootTouchWire.ack(it,sequence,status,1000)
        RootTouchWire.readAck(ByteArrayInputStream(it.toByteArray()))
    }
    private inner class Fixture {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val now = AtomicLong(1000)
        val sent = CopyOnWriteArrayList<TouchSample>()
        val receipts = CopyOnWriteArrayList<ContinuousTouchSupervisor.Receipt>()
        val pipes = CopyOnWriteArrayList<FakePipe>()
        @Volatile var current = true
        var createFailure: Exception? = null
        var ackFailure = false
        var cleanupConfirmed = true
        var holdFirst: CompletableDeferred<Unit>? = null
        var outboundThrows = false
        inner class FakePipe : TouchPipe {
            @Volatile var closed = false
            override suspend fun send(sample: TouchSample): RootTouchWire.Ack {
                sent.add(sample)
                if (sent.size == 1) holdFirst?.await()
                if (ackFailure) throw IOException("fixture private data")
                return ack(sample.sequence, if(sample.action == 4) 2 else if(sample.action == 3) 3 else 1)
            }
            override suspend fun closeAndConfirm(): Boolean { closed = true; return cleanupConfirmed }
        }
        val supervisor = ContinuousTouchSupervisor(scope, TouchPipeFactory {
            createFailure?.let { throw it }
            FakePipe().also { pipes.add(it) }
        }, {now.get()}, {current}, { _, receipt ->
            receipts.add(receipt)
            if(outboundThrows) throw IOException("outbound transport closed")
        })
        fun send(seq: Int, action: Int, gesture: Long = 1) = supervisor.offer(binding.owner,binding.captureEpoch,seq,gesture,action,100,120)
        suspend fun ready() {
            assertTrue(supervisor.open(binding))
            eventually { receipts.any { it.status == 0 } }
        }
        suspend fun finish() {
            holdFirst?.complete(Unit)
            supervisor.close()
            scope.cancel()
        }
    }
    private suspend fun eventually(predicate: () -> Boolean) = withTimeout(2000) { while(!predicate()) delay(5) }

    @Test fun `construction is lazy and one owner uses one pipe for many moves`() = runBlocking {
        val f = Fixture()
        assertTrue(f.pipes.isEmpty())
        try {
            f.ready()
            f.send(1,0)
            eventually {f.sent.size == 1}
            for(seq in 2..2001) f.send(seq,2)
            f.send(2002,1)
            eventually {f.sent.lastOrNull()?.action == 1}
            assertEquals(1,f.pipes.size)
            assertTrue(f.sent.size < 100)
            assertEquals(2002,f.sent.last().sequence)
        } finally {f.finish()}
        assertTrue(f.pipes.single().closed)
    }

    @Test fun `blocked injector coalesces motion and keeps up behind latest move`() = runBlocking {
        val f = Fixture()
        try {
            f.holdFirst = CompletableDeferred()
            f.ready()
            f.send(1,0)
            eventually {f.sent.size == 1}
            for(seq in 2..10001) f.send(seq,2)
            f.send(10002,1)
            f.holdFirst!!.complete(Unit)
            eventually {f.sent.size == 3}
            assertEquals(listOf(1,10001,10002),f.sent.map {it.sequence})
            assertEquals(listOf(0,2,1),f.sent.map {it.action})
        } finally {f.finish()}
    }

    @Test fun `wrong owner cannot invalidate active owner`() = runBlocking {
        val f = Fixture()
        try {
            f.ready()
            assertEquals(ContinuousTouchMailbox.Admission.WRONG_OWNER, f.supervisor.offer("another_owner",binding.captureEpoch,1,1,0,100,100))
            f.send(1,0)
            eventually {f.sent.size == 1}
            assertFalse(f.pipes.single().closed)
        } finally {f.finish()}
    }

    @Test fun `invalidate clears queued movement while already sent down completes`() = runBlocking {
        val f = Fixture()
        try {
            f.holdFirst = CompletableDeferred()
            f.ready(); f.send(1,0)
            eventually {f.sent.size == 1}
            f.send(2,2); f.send(3,1)
            f.supervisor.invalidate()
            f.holdFirst!!.complete(Unit)
            eventually {f.pipes.single().closed}
            assertEquals(listOf(0),f.sent.map {it.action})
            assertEquals(ContinuousTouchMailbox.Admission.RETIRED,f.send(4,0,2))
        } finally {f.finish()}
    }

    @Test fun `stale capture closes pipe without another motion`() = runBlocking {
        val f = Fixture()
        try {
            f.ready()
            f.current = false
            eventually {f.pipes.single().closed}
            assertTrue(f.sent.isEmpty())
            assertFalse(f.supervisor.open(binding))
        } finally {f.finish()}
    }

    @Test fun `lease expiry retires locally even without new offer`() = runBlocking {
        val f = Fixture()
        try {
            f.ready();f.send(1,0)
            eventually {f.sent.size == 1}
            f.now.set(2500)
            eventually {f.pipes.single().closed}
            assertEquals(ContinuousTouchMailbox.Admission.RETIRED,f.send(2,2))
        } finally {f.finish()}
    }

    @Test fun `unknown input is never replayed and cleanup confirmation is separate`() = runBlocking {
        val f = Fixture()
        try {
            f.ackFailure = true
            f.ready();f.send(1,0)
            eventually {f.pipes.single().closed}
            assertEquals(1,f.sent.size)
            assertTrue(f.receipts.any {it.status == 6})
            assertTrue(f.receipts.any {it.status == 6 && it.sequence == 1 && it.stage == ContinuousTouchSupervisor.Stage.INPUT})
            assertTrue(f.receipts.any {it.status == 3 && it.stage == ContinuousTouchSupervisor.Stage.RELEASE})
            assertFalse(f.supervisor.needsReset())
            assertEquals(ContinuousTouchMailbox.Admission.RETIRED,f.send(2,2))
        } finally {f.finish()}
    }

    @Test fun `unconfirmed cleanup permanently blocks implicit takeover`() = runBlocking {
        val f = Fixture()
        try {
            f.cleanupConfirmed = false
            f.ready()
            f.supervisor.close()
            assertTrue(f.supervisor.needsReset())
            assertFalse(f.supervisor.open(binding.copy(owner="other_012345")))
            assertEquals(1,f.pipes.size)
            assertEquals(6,f.receipts.last().status)
        } finally {f.finish()}
    }

    @Test fun `unknown startup cleanup blocks second process without emitting cancelled`() = runBlocking {
        val f = Fixture()
        try {
            f.createFailure = TouchPipeCleanupUnknownException()
            assertTrue(f.supervisor.open(binding))
            eventually {f.supervisor.needsReset()}
            f.supervisor.close()
            assertFalse(f.supervisor.open(binding))
            assertTrue(f.receipts.none {it.status == 0 || it.status == 3})
        } finally {f.finish()}
    }

    @Test fun `outbound receipt failure cannot prevent pipe cleanup`() = runBlocking {
        val f = Fixture()
        try {
            f.outboundThrows = true
            f.ready();f.send(1,0)
            eventually {f.sent.size == 1}
            f.supervisor.close()
            assertTrue(f.pipes.single().closed)
        } finally {f.finish()}
    }

    @Test fun `inactive application scope cannot advertise or retain an owner`() = runBlocking {
        val f = Fixture()
        f.scope.cancel()
        assertFalse(f.supervisor.open(binding))
        assertTrue(f.pipes.isEmpty())
        assertEquals(ContinuousTouchMailbox.Admission.RETIRED,f.send(1,0))
    }

    @Test fun `neither another owner nor duplicate open silently resets an active pipe`() = runBlocking {
        val f = Fixture()
        try {
            f.ready()
            assertFalse(f.supervisor.open(binding))
            assertFalse(f.supervisor.open(binding.copy(owner="another_owner")))
            assertEquals(1,f.pipes.size)
            assertFalse(f.pipes.single().closed)
            f.supervisor.close()
            assertTrue(f.supervisor.open(binding.copy(owner="another_owner")))
            eventually {f.pipes.size == 2}
            assertTrue(f.pipes.first().closed)
        } finally {f.finish()}
    }
}
