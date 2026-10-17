package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class DirectVideoLeaseTest {
    @Test fun finiteProbeCannotBorrowLiveRenewal() {
        val lease = DirectVideoLease(1000, 30000, false)
        assertFalse(lease.renew(1, 30000, 2000, 2000))
        assertEquals(31000L, lease.expiresAt)
    }
    @Test fun renewedVideoOutlivesThirtySecondsWithoutRevivingExpiredOwnership() {
        val lease = DirectVideoLease(1000, 30000, true)
        assertTrue(lease.renew(1, 30000, 6000, 6001))
        assertTrue(lease.renew(2, 30000, 35000, 35001))
        assertTrue(lease.valid(60000))
        assertFalse(lease.renew(3, 30000, 65000, 65000))
        assertFalse(lease.valid(65000))
    }
    @Test fun duplicateOutOfOrderAndDelayedMailboxRenewalsCannotExtendTheLease() {
        val lease = DirectVideoLease(1000, 30000, true)
        assertTrue(lease.renew(2, 30000, 6000, 6001))
        val expires = lease.expiresAt
        for (sequence in listOf(1, 2, 0, 1000001)) assertFalse(lease.renew(sequence, 30000, 7000, 7001))
        assertFalse(lease.renew(3, 30000, 7000, 36000))
        assertEquals(expires, lease.expiresAt)
    }
    @Test fun renewedNativePeerStillHasAnAbsoluteEightHourBudget() {
        val lease = DirectVideoLease(0, 30000, true)
        var sequence = 1
        var now = 20000L
        while (now < DirectVideoLease.MAX_LIFETIME_MS) {
            assertTrue(lease.renew(sequence++, 30000, now, now))
            now += 20000
        }
        assertEquals(DirectVideoLease.MAX_LIFETIME_MS, lease.expiresAt)
        assertFalse(lease.valid(DirectVideoLease.MAX_LIFETIME_MS))
    }
}
