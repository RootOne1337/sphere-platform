package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Test

class LegacyVideoDeliveryLeaseTest {
    @Test fun expiredSuppressionResumesLegacyWithExactlyOneRecoveryRequest() {
        val lease = LegacyVideoDeliveryLease()
        assertTrue(lease.observe(0).sendLegacy)
        assertTrue(lease.renew(false, 100, 5000))
        assertFalse(lease.observe(5099).sendLegacy)
        assertEquals(LegacyVideoDeliveryLease.Decision(true, true), lease.observe(5100))
        assertEquals(LegacyVideoDeliveryLease.Decision(true, false), lease.observe(5101))
    }

    @Test fun newLegacyViewerSurvivesLateOffRenewal() {
        val lease = LegacyVideoDeliveryLease()
        lease.renew(false, 0, 5000)
        assertFalse(lease.observe(1).sendLegacy)
        lease.requireLegacy(100)
        lease.renew(false, 101, 10000)
        assertTrue(lease.observe(102).sendLegacy)
        lease.renew(false, 10000, 10000)
        assertTrue(lease.observe(12099).sendLegacy)
        assertFalse(lease.observe(12100).sendLegacy)
    }

    @Test fun failedOrMissingRenewalNeverDisablesFallbackPermanently() {
        for (ttl in listOf(-1, 0, 10001, Int.MAX_VALUE)) {
            val lease = LegacyVideoDeliveryLease()
            lease.renew(false, 1, 5000)
            assertFalse(lease.observe(2).sendLegacy)
            assertFalse(lease.renew(false, 3, ttl))
            assertEquals(LegacyVideoDeliveryLease.Decision(true, true), lease.observe(4))
        }
    }

    @Test fun clockRollbackAndOverflowFailOpen() {
        val lease = LegacyVideoDeliveryLease()
        lease.renew(false, 100, 5000)
        assertFalse(lease.observe(200).sendLegacy)
        assertTrue(lease.observe(199).sendLegacy)
        assertFalse(lease.renew(false, Long.MAX_VALUE, 10))
        assertTrue(lease.observe(Long.MAX_VALUE).sendLegacy)
    }

    @Test fun explicitEnableRestoresRecoveryAndOtherOwnersStartEnabled() {
        val old = LegacyVideoDeliveryLease()
        old.renew(false, 0, 5000)
        assertFalse(old.observe(1).sendLegacy)
        old.renew(true, 2, 5000)
        assertTrue(old.observe(3).requestKeyFrame)
        assertFalse(old.observe(4).requestKeyFrame)
        assertTrue(LegacyVideoDeliveryLease().observe(5).sendLegacy)
    }
}
