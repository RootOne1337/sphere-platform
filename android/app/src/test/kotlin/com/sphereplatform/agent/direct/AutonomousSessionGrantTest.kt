package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class AutonomousSessionGrantTest {
    private val session = "peer_session_1234"
    private val instance = "device_instance_1234"
    private val capture = "capture_epoch_1234"
    private fun grant(control: Boolean = true, lifetime: Long = AutonomousSessionGrant.MAX_LIFETIME_MS) =
        AutonomousSessionGrant(session, instance, capture, control, 1000, lifetime)

    @Test fun `server admission alone does not authorize input`() {
        val g=grant()
        assertTrue(g.valid(instance,capture,1000))
        assertFalse(g.maySendInput(instance,capture,1000))
        assertFalse(g.establish("foreign_peer_1234",instance,capture,1001))
        assertFalse(g.established)
        assertTrue(g.establish(session,instance,capture,1002))
        assertTrue(g.maySendInput(instance,capture,1002))
    }
    @Test fun `established peer survives server loss beyond all legacy lease deadlines`() {
        val g=grant()
        assertTrue(g.establish(session,instance,capture,1001))
        g.brokerLost(1002)
        for (elapsed in listOf(1500L,30_000L,60_000L,300_000L,3_600_000L)) {
            assertTrue(g.valid(instance,capture,1000+elapsed))
            assertTrue(g.maySendInput(instance,capture,1000+elapsed))
        }
        assertFalse(g.brokerAvailable)
        assertNull(g.ended)
    }
    @Test fun `pending signaling cannot turn into an offline peer`() {
        val g=grant()
        g.brokerLost(1001)
        assertEquals(AutonomousSessionGrant.End.PEER_LOST,g.ended)
        assertFalse(g.establish(session,instance,capture,1002))
    }
    @Test fun `setup expires at exact deadline`() {
        val g=grant()
        assertTrue(g.valid(instance,capture,30_999))
        assertFalse(g.establish(session,instance,capture,31_000))
        assertEquals(AutonomousSessionGrant.End.SETUP_EXPIRED,g.ended)
    }
    @Test fun `fixed authorization limit cannot be renewed by reconnect or traffic`() {
        val g=grant(lifetime=5000)
        assertTrue(g.establish(session,instance,capture,1001))
        g.brokerLost(1002)
        assertTrue(g.brokerRestored(instance,capture,5999))
        assertFalse(g.maySendInput(instance,capture,6000))
        assertEquals(AutonomousSessionGrant.End.EXPIRED,g.ended)
        assertFalse(g.brokerRestored(instance,capture,6001))
        assertFalse(g.establish(session,instance,capture,1001))
    }
    @Test fun `read only session survives an outage without acquiring input authority`() {
        val g=grant(control=false)
        assertTrue(g.establish(session,instance,capture,1001))
        g.brokerLost(1002)
        assertTrue(g.valid(instance,capture,60_000))
        assertFalse(g.maySendInput(instance,capture,60_000))
    }
    @Test fun `same identity reconnect preserves a peer but changed instance revokes it`() {
        val g=grant()
        assertTrue(g.establish(session,instance,capture,1001))
        g.brokerLost(1002)
        assertTrue(g.brokerRestored(instance,capture,1003))
        assertTrue(g.established)
        assertTrue(g.brokerAvailable)
        assertFalse(g.brokerRestored("new_instance_1234",capture,1004))
        assertEquals(AutonomousSessionGrant.End.INSTANCE_CHANGED,g.ended)
    }
    @Test fun `capture restart of equal dimensions cannot borrow an old grant`() {
        val g=grant()
        assertTrue(g.establish(session,instance,capture,1001))
        assertFalse(g.valid(instance,"capture_epoch_5678",1002))
        assertEquals(AutonomousSessionGrant.End.CAPTURE_CHANGED,g.ended)
    }
    @Test fun `clock rollback is terminal and cannot extend the offline grant`() {
        val g=grant()
        assertTrue(g.establish(session,instance,capture,1002))
        assertFalse(g.valid(instance,capture,1001))
        assertEquals(AutonomousSessionGrant.End.CLOCK_REGRESSION,g.ended)
        assertFalse(g.valid(instance,capture,1003))
    }
    @Test fun `explicit peer loss and permission revocation are terminal and keep first reason`() {
        for (reason in listOf(AutonomousSessionGrant.End.PEER_LOST,AutonomousSessionGrant.End.REVOKED)) {
            val g=grant()
            assertTrue(g.establish(session,instance,capture,1001))
            g.revoke(reason); g.revoke(AutonomousSessionGrant.End.EXPIRED)
            assertEquals(reason,g.ended)
            assertFalse(g.maySendInput(instance,capture,1002))
        }
    }
    @Test fun `invalid identities lifetimes and overflow are rejected`() {
        val constructors: List<()->Unit> = listOf(
            { AutonomousSessionGrant("x",instance,capture,true,1000,5000) },
            { AutonomousSessionGrant(session,"x",capture,true,1000,5000) },
            { AutonomousSessionGrant(session,instance,"x",true,1000,5000) },
            { grant(lifetime=0) }, { grant(lifetime=AutonomousSessionGrant.MAX_LIFETIME_MS+1) },
            { AutonomousSessionGrant(session,instance,capture,true,-1,5000) },
            { AutonomousSessionGrant(session,instance,capture,true,Long.MAX_VALUE,5000) },
        )
        for (create in constructors) {
            try { create(); fail("must reject invalid authority") } catch (_: IllegalArgumentException) { }
        }
    }
}
