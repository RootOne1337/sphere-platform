package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test

class RootKeyboardSessionTest {
    private data class Key(val action: Int, val code: Int, val meta: Int, val down: Long)
    private class Fixture {
        val keys = mutableListOf<Key>()
        var refuse = false
        val session = RootTouchSession(960,540,1000,{ _,_,_,_,_ -> true }, { true }, { action,code,meta,down,_ ->
            keys += Key(action,code,meta,down); !refuse
        })
        fun send(seq: Int, action: Int, code: Int = 29, meta: Int = 0) = session.apply(seq,0,action,code,meta,1000L+seq)
    }
    @Test fun `held modifiers letters repeated down and exact up preserve physical edges`() {
        val f=Fixture()
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED,f.send(1,6,113,4096))
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED,f.send(2,6,29,4096))
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED,f.send(3,6,29,4096))
        assertEquals(2,f.keys.size)
        f.send(4,7,29,4096);f.send(5,7,113)
        assertEquals(listOf(0,0,1,1),f.keys.map { it.action })
        assertEquals(1002L,f.keys[2].down)
        assertEquals(RootTouchSession.Result.CANCELLED,f.session.close(1010))
        assertEquals(0,f.session.cleanupExitCode())
    }
    @Test fun `reset releases all keys and late up never replays a held edge`() {
        val f=Fixture();f.send(1,6,59,1);f.send(2,6,29,1)
        f.send(3,8,0);f.send(4,7,29)
        assertEquals(listOf(0,0,-1,-1),f.keys.map { it.action })
        assertEquals(0,f.session.close(1010).let { f.session.cleanupExitCode() })
    }
    @Test fun `watchdog releases keys and uncertainty cannot admit another native group`() {
        val f=Fixture();f.send(1,6);f.refuse=true
        assertEquals(RootTouchSession.Result.UNKNOWN,f.session.tick(2501))
        assertEquals(listOf(0,-1),f.keys.map { it.action })
        assertEquals(2,f.session.cleanupExitCode())
    }
    @Test fun `power key and unknown meta do not reach injector`() {
        for ((key,meta) in listOf(26 to 0,29 to 8)) {
            val f=Fixture();assertEquals(RootTouchSession.Result.REJECTED,f.send(1,6,key,meta));assertTrue(f.keys.isEmpty())
        }
    }
}
