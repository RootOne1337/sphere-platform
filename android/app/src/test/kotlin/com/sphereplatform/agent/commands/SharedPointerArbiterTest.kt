package com.sphereplatform.agent.commands

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicLong

class SharedPointerArbiterTest {
    private val a = "participant_A_1234"
    private val b = "participant_B_1234"
    private val c = "participant_C_1234"
    private class Fixture {
        val now = AtomicLong(1000)
        val sent = mutableListOf<SharedPointerArbiter.NativeAction>()
        var failAction: Int? = null
        var thrown = false
        var delayCancel = 0L
        var barrier: CompletableDeferred<Unit>? = null
        val arbiter = SharedPointerArbiter(960,540,now::get) {
            sent += it
            barrier?.await()
            if (it.action == RootTouchSession.CANCEL) now.addAndGet(delayCancel)
            if (thrown) throw IllegalStateException("private fixture exception")
            it.action != failAction
        }
        fun attach(id: String, control: Boolean = true, deadline: Long = 600_000) = arbiter.attach(id,deadline,control)
        suspend fun event(id: String, sequence: Int, action: Int, gesture: Long = 1,
                          x: Int = 100, y: Int = 120, receivedAt: Long = now.get()) =
            arbiter.offer(SharedPointerArbiter.Event(id,sequence,gesture,action,x,y,receivedAt))
    }

    @Test fun `admission of ten participants does not acquire or displace the pointer`() {
        val f=Fixture()
        for (i in 0 until 10) assertTrue(f.attach("participant_${i}_1234"))
        assertEquals(10,f.arbiter.participantCount)
        assertFalse(f.attach("participant_11_1234"))
        assertFalse(f.attach("participant_0_1234"))
        assertNull(f.arbiter.heldParticipant)
        assertTrue(f.sent.isEmpty())
    }
    @Test fun `latest received DOWN cancels the previous gesture before native delivery`() = runBlocking {
        val f=Fixture(); assertTrue(f.attach(a)); assertTrue(f.attach(b))
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(a,1,0).single().outcome)
        val takeover=f.event(b,1,0)
        assertEquals(listOf(0,3,0),f.sent.map { it.action })
        assertEquals(listOf(1L,1L,2L),f.sent.map { it.gesture })
        assertEquals(a,takeover[0].participant)
        assertEquals(SharedPointerArbiter.Outcome.INTERRUPTED,takeover[0].outcome)
        assertEquals(b,takeover[1].participant)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,takeover[1].outcome)
        assertEquals(b,f.arbiter.heldParticipant)
        assertEquals(2,f.arbiter.participantCount)
    }
    @Test fun `old MOVE UP and held heartbeat cannot reacquire an interrupted gesture`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0); f.event(b,1,0)
        for ((seq,action) in listOf(2 to 2,3 to 1,4 to 4))
            assertEquals(SharedPointerArbiter.Outcome.INTERRUPTED,f.event(a,seq,action).single().outcome)
        assertEquals(listOf(0,3,0),f.sent.map { it.action })
        assertEquals(b,f.arbiter.heldParticipant)
        assertEquals(2,f.arbiter.participantCount)
    }
    @Test fun `interrupted participant can start a new gesture without replacing its session`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0); f.event(b,1,0)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(a,2,0,2).last().outcome)
        assertEquals(listOf(0,3,0,3,0),f.sent.map { it.action })
        assertEquals(a,f.arbiter.heldParticipant)
        assertEquals(2,f.arbiter.participantCount)
    }
    @Test fun `idle heartbeat from another client does not steal a gesture or claim native execution`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0)
        assertEquals(SharedPointerArbiter.Outcome.ALIVE,f.event(b,1,4,0).single().outcome)
        assertEquals(a,f.arbiter.heldParticipant)
        assertEquals(1,f.sent.size)
    }
    @Test fun `closing one idle client preserves another held client`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0)
        assertEquals(SharedPointerArbiter.Outcome.CLOSED,f.arbiter.remove(b).single().outcome)
        assertEquals(a,f.arbiter.heldParticipant)
        assertEquals(1,f.arbiter.participantCount)
        assertEquals(listOf(0),f.sent.map { it.action })
    }
    @Test fun `closing the held client confirms CANCEL and leaves other clients available`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0)
        assertEquals(SharedPointerArbiter.Outcome.CLOSED,f.arbiter.remove(a).single().outcome)
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertNull(f.arbiter.heldParticipant)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(b,1,0).single().outcome)
    }
    @Test fun `read only and unknown participant cannot affect another pointer`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b,control=false)
        f.event(a,1,0)
        for (id in listOf(b,c)) assertEquals(SharedPointerArbiter.Outcome.DENIED,f.event(id,1,0).single().outcome)
        assertEquals(a,f.arbiter.heldParticipant)
        assertEquals(listOf(0),f.sent.map { it.action })
    }
    @Test fun `duplicate input is not replayed and invalidates only its own participant`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.event(a,1,0)
        assertEquals(SharedPointerArbiter.Outcome.INVALID,f.event(a,1,0).single().outcome)
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertEquals(1,f.arbiter.participantCount)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(b,1,0).single().outcome)
    }
    @Test fun `malformed input from idle client cannot cancel another client's held pointer`() = runBlocking {
        for (event in listOf(Triple(2,1L,-1),Triple(0,0L,100),Triple(9,1L,100))) {
            val f=Fixture(); f.attach(a); f.attach(b); f.event(a,1,0)
            assertEquals(SharedPointerArbiter.Outcome.INVALID,f.event(b,1,event.first,event.second,event.third).single().outcome)
            assertEquals(a,f.arbiter.heldParticipant)
            assertEquals(listOf(0),f.sent.map { it.action })
            assertEquals(1,f.arbiter.participantCount)
        }
    }
    @Test fun `uncertain cancellation never admits the new DOWN or reports it applied`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b); f.event(a,1,0)
        f.failAction=RootTouchSession.CANCEL
        val result=f.event(b,1,0)
        assertTrue(result.all { it.outcome==SharedPointerArbiter.Outcome.UNKNOWN })
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertTrue(f.arbiter.fenced)
        assertFalse(f.attach(c))
        assertEquals(SharedPointerArbiter.Outcome.DENIED,f.event(b,2,0,2).single().outcome)
    }
    @Test fun `unknown DOWN outcome is never repeated and pipe exceptions expose no data`() = runBlocking {
        for (exception in listOf(false,true)) {
            val f=Fixture(); f.attach(a); f.attach(b)
            f.failAction=RootTouchSession.DOWN; f.thrown=exception
            assertTrue(f.event(a,1,0).all { it.outcome==SharedPointerArbiter.Outcome.UNKNOWN })
            assertTrue(f.arbiter.fenced)
            assertEquals(1,f.sent.size)
            f.event(a,2,0,2)
            assertEquals(1,f.sent.size)
        }
    }
    @Test fun `expired or future queued event is not injected and preserves other participants`() = runBlocking {
        for (received in listOf(500L,1001L)) {
            val f=Fixture(); f.attach(a); f.attach(b)
            assertEquals(SharedPointerArbiter.Outcome.EXPIRED,f.event(a,1,0,receivedAt=received).single().outcome)
            assertEquals(1,f.arbiter.participantCount)
            assertTrue(f.sent.isEmpty())
            assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(b,1,0).single().outcome)
        }
    }
    @Test fun `slow confirmed CANCEL cannot carry replacement past its event deadline`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b); f.event(a,1,0)
        f.delayCancel=500
        val result=f.event(b,1,0)
        assertEquals(listOf(SharedPointerArbiter.Outcome.INTERRUPTED,SharedPointerArbiter.Outcome.EXPIRED),result.map { it.outcome })
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertNull(f.arbiter.heldParticipant)
        assertFalse(f.arbiter.fenced)
    }
    @Test fun `slow confirmed CANCEL rechecks replacement grant before DOWN`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b,deadline=1100); f.event(a,1,0)
        f.delayCancel=100
        assertEquals(SharedPointerArbiter.Outcome.EXPIRED,f.event(b,1,0).last().outcome)
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertFalse(f.arbiter.fenced)
    }
    @Test fun `per participant idle expiry is independent from another client heartbeat`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b); f.event(a,1,0)
        f.now.set(2400); f.event(b,1,4,0)
        f.now.set(2500)
        val expired=f.arbiter.expire()
        assertEquals(a,expired.single().participant)
        assertEquals(SharedPointerArbiter.Outcome.EXPIRED,expired.single().outcome)
        assertEquals(listOf(0,3),f.sent.map { it.action })
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(b,2,0).single().outcome)
    }
    @Test fun `local clock regression fences every participant without injecting stale input`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b); f.event(a,1,0)
        f.now.set(999)
        assertTrue(f.arbiter.expire().all { it.outcome==SharedPointerArbiter.Outcome.UNKNOWN })
        assertTrue(f.arbiter.fenced)
        assertEquals(listOf(0),f.sent.map { it.action })
    }
    @Test fun `clock rollback during new admission cannot preserve old pointer authority`() = runBlocking {
        val f=Fixture(); f.attach(a); f.event(a,1,0)
        f.now.set(999)
        assertFalse(f.attach(b))
        assertTrue(f.arbiter.fenced)
        assertEquals(0,f.arbiter.participantCount)
        assertEquals(listOf(0),f.sent.map { it.action })
    }
    @Test fun `ten clients repeatedly take over with one deterministic native gesture at a time`() = runBlocking {
        val f=Fixture()
        val ids=(0 until 10).map { "participant_${it}_1234" }
        ids.forEach { assertTrue(f.attach(it)) }
        repeat(100) { index ->
            val id=ids[index%ids.size]
            val seq=index/ids.size+1
            assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(id,seq,0,seq.toLong()).last().outcome)
            assertEquals(id,f.arbiter.heldParticipant)
            assertEquals(10,f.arbiter.participantCount)
        }
        assertEquals(100,f.sent.count { it.action==RootTouchSession.DOWN })
        assertEquals(99,f.sent.count { it.action==RootTouchSession.CANCEL })
        assertEquals((1L..100L).toList(),f.sent.filter { it.action==RootTouchSession.DOWN }.map { it.gesture })
    }
    @Test fun `overlapping caller cannot race a suspended native operation`() = runBlocking {
        val f=Fixture(); f.attach(a); f.attach(b)
        f.barrier=CompletableDeferred()
        val first=async { f.event(a,1,0) }
        kotlinx.coroutines.yield()
        assertEquals(SharedPointerArbiter.Outcome.BUSY,f.event(b,1,0).single().outcome)
        assertEquals(1,f.sent.size)
        f.barrier!!.complete(Unit)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,first.await().single().outcome)
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,f.event(b,1,0).last().outcome)
    }
}
