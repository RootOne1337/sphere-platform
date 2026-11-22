package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test

class RootKeySessionTest {
    private class Fixture {
        val keys = mutableListOf<Pair<Int, Int>>()
        var failAction: Int? = null
        val session = RootTouchSession(2, 2, 1000, { _, _, _, _, _ -> true }, { true },
            { action, code, _, _, _ -> keys += action to code; action != failAction })
        fun key(sequence: Int = 1, code: Int = 187, gesture: Long = 0, meta: Int = 0) =
            session.apply(sequence, gesture, RootTouchSession.KEY_TAP, code, meta, 1000L + sequence)
    }
    @Test fun `navigation codes are not interpreted as video coordinates and both key edges are acknowledged`() {
        val f = Fixture()
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.key())
        assertEquals(listOf(0 to 187, 1 to 187), f.keys)
        assertEquals(RootTouchSession.Result.HEARTBEAT_ACCEPTED, f.session.apply(2, 0, 4, 0, 0, 1002))
        assertEquals(RootTouchSession.Result.CANCELLED, f.session.close(1003))
        assertEquals(0, f.session.cleanupExitCode())
    }
    @Test fun `false down or up is unknown and releases the uncertain key without another key down`() {
        for (action in listOf(0, 1)) {
            val f = Fixture(); f.failAction = action
            assertEquals(RootTouchSession.Result.UNKNOWN, f.key())
            assertEquals(1, f.keys.count { it.first == 0 })
            assertEquals(-1 to 187, f.keys.last())
            assertEquals(0, f.session.cleanupExitCode())
            assertEquals(RootTouchSession.Result.REJECTED, f.key(2))
        }
    }
    @Test fun `failed cleanup remains unknown and never authorizes another input`() {
        val events = mutableListOf<Int>()
        val state = RootTouchSession(2, 2, 1000, { _, _, _, _, _ -> true }, { true },
            { action, _, _, _, _ -> events += action; false })
        assertEquals(RootTouchSession.Result.UNKNOWN, state.apply(1, 0, 5, 3, 0, 1001))
        assertEquals(listOf(0, -1), events)
        assertEquals(2, state.cleanupExitCode())
    }
    @Test fun `power key modifiers wrong nonce duplicates and a held pointer refuse key injection`() {
        for ((code, gesture, meta) in listOf(Triple(26, 0L, 0), Triple(3, 1L, 0), Triple(3, 0L, 1))) {
            val f = Fixture()
            assertEquals(RootTouchSession.Result.REJECTED, f.key(code = code, gesture = gesture, meta = meta))
            assertTrue(f.keys.isEmpty())
        }
        val f = Fixture(); assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.key())
        assertEquals(RootTouchSession.Result.REJECTED, f.key())
        assertEquals(2, f.keys.size)
        val held = Fixture(); held.session.apply(1, 1, 0, 1, 1, 1001)
        assertEquals(RootTouchSession.Result.REJECTED, held.key(2))
        assertTrue(held.keys.isEmpty())
    }
}
