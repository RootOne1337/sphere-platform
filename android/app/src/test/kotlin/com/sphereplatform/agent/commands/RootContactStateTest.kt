package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test

class RootContactStateTest {
    private data class Event(val action: Int, val ids: List<Int>, val xs: List<Int>, val down: Long, val at: Long)
    private class Fixture {
        val events = mutableListOf<Event>()
        val legacy = mutableListOf<Int>()
        var geometry = true
        var reject = -1
        val session = RootTouchSession(960, 540, 1000, { action, _, _, _, _ -> legacy += action; true },
            { geometry }, null, { action, ids, xs, _, down, at ->
                events += Event(action, ids.toList(), xs.toList(), down, at)
                action != reject
            })
        fun send(seq: Int, id: Int, action: Int, x: Int = 100, gesture: Long = 1, at: Long = 1000L + seq) =
            session.apply(seq, gesture, RootContactState.encode(id, action), x, 300, at)
    }

    @Test fun `stick camera and button share one downTime and preserve other contacts on move`() {
        val f = Fixture()
        for (id in 0..2) assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.send(id+1, id, 0, x=100+id*200))
        f.send(4, 1, 2, x=450)
        assertEquals(listOf(0, 261, 517, 2), f.events.map { it.action })
        assertEquals(listOf(0,1,2), f.events.last().ids)
        assertEquals(listOf(100,450,500), f.events.last().xs)
        assertTrue(f.events.all { it.down == 1001L })
        assertTrue(f.session.isHeld)
        assertTrue(f.legacy.isEmpty())
    }

    @Test fun `lifting first finger preserves camera identity and lifting last emits up`() {
        val f = Fixture()
        f.send(1,0,0); f.send(2,1,0)
        f.send(3,0,1)
        assertEquals(6, f.events.last().action)
        assertEquals(listOf(0,1), f.events.last().ids)
        assertTrue(f.session.isHeld)
        f.send(4,1,2)
        assertEquals(listOf(1), f.events.last().ids)
        f.send(5,1,1)
        assertEquals(1, f.events.last().action)
        assertFalse(f.session.isHeld)
    }

    @Test fun `heartbeat retains contacts without repeating down or changing downTime`() {
        val f = Fixture()
        f.send(1,0,0)
        assertEquals(RootTouchSession.Result.HEARTBEAT_ACCEPTED, f.session.apply(2,1,4,0,0,2000))
        assertEquals(1, f.events.size)
        f.send(3,0,2,at=2001)
        assertEquals(1001L, f.events.last().down)
    }

    @Test fun `duplicate down and stale gesture cancel all and cannot replay`() {
        for (stale in listOf(false,true)) {
            val f = Fixture(); f.send(1,0,0); f.send(2,1,0)
            assertEquals(RootTouchSession.Result.REJECTED,
                if (stale) f.send(3,1,2,gesture=2) else f.send(3,1,0))
            assertEquals(3, f.events.last().action)
            assertEquals(listOf(0,1), f.events.last().ids)
            assertEquals(RootTouchSession.Result.REJECTED,f.send(4,2,0))
            assertEquals(0,f.session.cleanupExitCode())
        }
    }

    @Test fun `lease geometry loss and clock regression cancel every held contact`() {
        for (mode in 0..2) {
            val f = Fixture(); f.send(1,0,0); f.send(2,1,0)
            if (mode==1) f.geometry=false
            assertNotNull(f.session.tick(if(mode==0) 2502 else if(mode==1) 1003 else 900))
            assertEquals(3,f.events.last().action)
            assertEquals(listOf(0,1),f.events.last().ids)
            assertFalse(f.session.isHeld)
        }
    }

    @Test fun `uncertain pointer down is included in cancel and uncertain release remains fenced`() {
        val f = Fixture(); f.send(1,0,0); f.reject=261
        assertEquals(RootTouchSession.Result.UNKNOWN,f.send(2,1,0))
        assertEquals(listOf(0,1),f.events.last().ids)
        assertEquals(3,f.events.last().action)
        assertEquals(0,f.session.cleanupExitCode())
        val g=Fixture(); g.send(1,0,0); g.send(2,1,0); g.reject=3
        assertEquals(RootTouchSession.Result.UNKNOWN,g.session.close(1100))
        assertEquals(2,g.session.cleanupExitCode())
        assertEquals(RootTouchSession.Result.UNKNOWN,g.session.close(1200))
    }

    @Test fun `legacy mode cannot accidentally activate contacts and cannot interleave a second down`() {
        val injected=mutableListOf<Int>()
        val legacy=RootTouchSession(960,540,1000,{ action,_,_,_,_->injected+=action;true },{true})
        assertEquals(RootTouchSession.Result.REJECTED,legacy.apply(1,1,16,100,300,1001))
        assertTrue(injected.isEmpty())
        val f=Fixture(); f.send(1,0,0)
        assertEquals(RootTouchSession.Result.REJECTED,f.session.apply(2,2,0,100,300,1002))
        assertEquals(3,f.events.last().action)
    }

    @Test fun `invalid contact id coordinates and missing down never inject an unowned move`() {
        assertEquals(-1,RootContactState.encode(3,0))
        for (mode in 0..2) {
            val f=Fixture()
            assertEquals(RootTouchSession.Result.REJECTED,when(mode) {
                0->f.send(1,0,2)
                1->f.send(1,0,0,x=960)
                else->f.session.apply(1,1,27,100,300,1001)
            })
            assertTrue(f.events.isEmpty())
        }
    }
}
