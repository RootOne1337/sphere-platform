package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class SharedInputMailboxTest {
    private val a="participant_A_1234"
    private val b="participant_B_1234"
    private fun event(id: String, sequence: Int, action: Int, gesture: Long = 1, receivedAt: Long = 1000) =
        SharedPointerArbiter.Event(id,sequence,gesture,action,100,120,receivedAt)
    private fun key(sequence: Int, operation: RemoteKeyboardCommand.Operation, code: Int = 29) =
        SharedPointerArbiter.Event(a, sequence, 0, RemoteKeyboardCommand.ACTION, 0, 0, 1000,
            RemoteKeyboardCommand(operation, 1, keyCode=code))

    @Test fun `four fast modifier edges survive a queued heartbeat without native drain`() {
        val m=SharedInputMailbox();m.register(a)
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,1,4,gesture=0)))
        for ((sequence, operation) in listOf(2 to RemoteKeyboardCommand.Operation.KEY_DOWN,
            3 to RemoteKeyboardCommand.Operation.KEY_DOWN,4 to RemoteKeyboardCommand.Operation.KEY_UP,
            5 to RemoteKeyboardCommand.Operation.KEY_UP)) {
            assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(key(sequence,operation)))
        }
        assertEquals(listOf(1,2,3,4,5),generateSequence { m.poll() }
            .map { (it as SharedInputMailbox.Work.Input).event.sequence }.toList())
    }
    @Test fun `keyboard capacity remains finite and reserves the final key release`() {
        val m=SharedInputMailbox();m.register(a)
        repeat(31) { assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(key(it+1,RemoteKeyboardCommand.Operation.KEY_DOWN))) }
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(key(32,RemoteKeyboardCommand.Operation.KEY_UP)))
        assertEquals(32,m.pendingCount())
        assertEquals(SharedInputMailbox.Admission.OVERFLOW,m.offer(key(33,RemoteKeyboardCommand.Operation.KEY_UP)))
        assertEquals(1,m.pendingCount());assertEquals(SharedInputMailbox.Work.Close(a),m.poll())
    }
    @Test fun `keyboard burst does not consume the four-entry pointer cleanup budget`() {
        val m=SharedInputMailbox();m.register(a)
        repeat(8) { assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(key(it+1,RemoteKeyboardCommand.Operation.KEY_DOWN))) }
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,9,0)))
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,10,2)))
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,11,4)))
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,12,1)))
        assertEquals(12,m.pendingCount())
    }

    @Test fun `unknown client cannot allocate queue memory`() {
        val m=SharedInputMailbox()
        repeat(10_000) { assertEquals(SharedInputMailbox.Admission.UNREGISTERED,m.offer(event(a,it+1,2))) }
        assertEquals(0,m.participantCount()); assertEquals(0,m.pendingCount()); assertNull(m.poll())
    }
    @Test fun `registration is bounded unique and identity checked`() {
        val m=SharedInputMailbox()
        assertFalse(m.register("x"))
        repeat(10) { assertTrue(m.register("participant_${it}_1234")) }
        assertFalse(m.register("participant_0_1234")); assertFalse(m.register("participant_11_1234"))
        assertEquals(10,m.participantCount())
    }
    @Test fun `MOVE flood coalesces separately per client within a fixed memory bound`() {
        val m=SharedInputMailbox(); m.register(a); m.register(b)
        repeat(10_000) { index ->
            m.offer(event(a,index+1,2)); m.offer(event(b,index+1,2))
            assertEquals(2,m.pendingCount())
        }
        assertEquals(10_000,(m.poll() as SharedInputMailbox.Work.Input).event.sequence)
        assertEquals(10_000,(m.poll() as SharedInputMailbox.Work.Input).event.sequence)
        assertNull(m.poll())
    }
    @Test fun `coalesced newer MOVE cannot overtake another clients earlier DOWN`() {
        val m=SharedInputMailbox(); m.register(a); m.register(b)
        m.offer(event(a,1,2)); m.offer(event(b,1,0)); m.offer(event(a,2,2))
        assertEquals(b,(m.poll() as SharedInputMailbox.Work.Input).event.participant)
        assertEquals(2,(m.poll() as SharedInputMailbox.Work.Input).event.sequence)
    }
    @Test fun `coalescing does not cross own DOWN UP or heartbeat barriers`() {
        val m=SharedInputMailbox(); m.register(a)
        m.offer(event(a,1,0)); m.offer(event(a,2,2)); m.offer(event(a,3,2)); m.offer(event(a,4,1))
        val inputs=generateSequence { m.poll() }.map { (it as SharedInputMailbox.Work.Input).event }.toList()
        assertEquals(listOf(0,2,1),inputs.map { it.action }); assertEquals(listOf(1,3,4),inputs.map { it.sequence })
    }
    @Test fun `fourth slot is reserved for a terminal event`() {
        val m=SharedInputMailbox(); m.register(a)
        m.offer(event(a,1,0)); m.offer(event(a,2,2)); m.offer(event(a,3,4))
        assertEquals(SharedInputMailbox.Admission.QUEUED,m.offer(event(a,4,1)))
        assertEquals(4,m.pendingCount())
        assertEquals(listOf(0,2,4,1),generateSequence { m.poll() }.map { (it as SharedInputMailbox.Work.Input).event.action }.toList())
    }
    @Test fun `overflow schedules one local cleanup and does not clear another queue`() {
        val m=SharedInputMailbox(); m.register(a); m.register(b)
        m.offer(event(a,1,0)); m.offer(event(a,2,2)); m.offer(event(a,3,4)); m.offer(event(b,1,0))
        assertEquals(SharedInputMailbox.Admission.OVERFLOW,m.offer(event(a,4,2)))
        assertEquals(SharedInputMailbox.Admission.RETIRED,m.offer(event(a,5,1)))
        assertEquals(2,m.pendingCount())
        assertEquals(b,(m.poll() as SharedInputMailbox.Work.Input).event.participant)
        assertEquals(a,(m.poll() as SharedInputMailbox.Work.Close).participant)
        assertEquals(1,m.participantCount()); assertNull(m.poll())
    }
    @Test fun `duplicate sequence retires only the offending client`() {
        val m=SharedInputMailbox(); m.register(a); m.register(b)
        m.offer(event(a,1,0)); m.offer(event(b,1,0))
        assertEquals(SharedInputMailbox.Admission.INVALID,m.offer(event(a,1,0)))
        assertEquals(b,(m.poll() as SharedInputMailbox.Work.Input).event.participant)
        assertEquals(a,(m.poll() as SharedInputMailbox.Work.Close).participant)
    }
    @Test fun `repeated close intent is idempotent and cannot be replaced by MOVE`() {
        val m=SharedInputMailbox(); m.register(a); m.offer(event(a,1,0))
        repeat(10_000) { assertTrue(m.retire(a)) }
        assertEquals(1,m.pendingCount()); assertEquals(SharedInputMailbox.Admission.RETIRED,m.offer(event(a,2,2)))
        assertEquals(SharedInputMailbox.Work.Close(a),m.poll()); assertNull(m.poll())
    }
    @Test fun `local reception time is retained through coalescing and never fabricated at dequeue`() {
        val m=SharedInputMailbox(); m.register(a)
        m.offer(event(a,1,2,receivedAt=1000)); m.offer(event(a,2,2,receivedAt=1001))
        assertEquals(1001L,(m.poll() as SharedInputMailbox.Work.Input).event.receivedAtMs)
    }
    @Test fun `global ordering does not rely on untrusted client gesture clocks`() {
        val m=SharedInputMailbox(); m.register(a); m.register(b)
        m.offer(event(a,1,0,gesture=Int.MAX_VALUE.toLong())); m.offer(event(b,1,0,gesture=1))
        assertEquals(a,(m.poll() as SharedInputMailbox.Work.Input).event.participant)
        assertEquals(b,(m.poll() as SharedInputMailbox.Work.Input).event.participant)
    }
    @Test fun `ten callback threads cannot exceed forty queue entries`() {
        val m=SharedInputMailbox(); val pool=Executors.newFixedThreadPool(10); val done=CountDownLatch(10)
        val ids=(0 until 10).map { "participant_${it}_1234" }; ids.forEach { assertTrue(m.register(it)) }
        try {
            for (id in ids) pool.submit { try { repeat(1000) { m.offer(event(id,it+1,2)) } } finally { done.countDown() } }
            assertTrue(done.await(5,TimeUnit.SECONDS))
            assertEquals(10,m.pendingCount()); assertEquals(10,m.participantCount())
            assertEquals(10,generateSequence { m.poll() }.count())
        } finally { pool.shutdownNow() }
    }
}
