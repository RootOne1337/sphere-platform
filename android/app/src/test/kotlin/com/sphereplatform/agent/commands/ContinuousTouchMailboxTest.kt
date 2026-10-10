package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test

class ContinuousTouchMailboxTest {
    private val binding = TouchBinding("owner_012345", "capture_012345", 960, 540, 0)
    private fun mailbox() = ContinuousTouchMailbox(binding, 1000)
    private fun ContinuousTouchMailbox.send(sequence: Int, action: Int, gesture: Long = 1, at: Long = 1000L + sequence,
                                            owner: String = binding.owner, epoch: String = binding.captureEpoch) =
        offer(owner, epoch, TouchSample(sequence, gesture, action, sequence.coerceIn(0, 959), 120, at))

    @Test fun `thousands of moves retain only down latest move and terminal up`() {
        val m = mailbox()
        m.send(1, 0)
        for (seq in 2..10001) {
            val admitted = m.send(seq, 2, at = 1100)
            assertEquals(if (seq == 2) ContinuousTouchMailbox.Admission.QUEUED else ContinuousTouchMailbox.Admission.COALESCED, admitted)
            assertEquals(2, m.size())
        }
        assertEquals(ContinuousTouchMailbox.Admission.QUEUED, m.send(10002, 1, at = 1101))
        assertEquals(3, m.size())
        assertEquals(listOf(1, 10001, 10002), List(3) { m.poll(1102)!!.sequence })
        assertNull(m.poll(1102))
    }

    @Test fun `coalescing never crosses a terminal or new gesture`() {
        val m = mailbox()
        m.send(1, 0)
        m.send(2, 2)
        m.send(3, 1)
        assertEquals(listOf(0, 2, 1), List(3) { m.poll(1100)!!.action })
        m.send(4, 0, gesture = 2)
        m.send(5, 2, gesture = 2)
        m.send(6, 3, gesture = 2)
        assertEquals(listOf(0, 2, 3), List(3) { m.poll(1100)!!.action })
    }

    @Test fun `terminal has a reserved slot after three pending events`() {
        val m = mailbox()
        m.send(1, 0)
        m.send(2, 2)
        m.send(3, 4)
        assertEquals(ContinuousTouchMailbox.Admission.QUEUED, m.send(4, 1))
        assertEquals(4, m.size())
        assertEquals(listOf(0, 2, 4, 1), List(4) { m.poll(1100)!!.action })
    }

    @Test fun `overflow retires all pending work rather than growing queue or replaying terminal`() {
        val m = mailbox()
        m.send(1, 0)
        m.send(2, 2)
        m.send(3, 4)
        assertEquals(ContinuousTouchMailbox.Admission.OVERFLOW, m.send(4, 2))
        assertTrue(m.isRetired())
        assertEquals(0, m.size())
        assertNull(m.poll(1100))
        assertEquals(ContinuousTouchMailbox.Admission.RETIRED, m.send(5, 1))
    }

    @Test fun `unrelated owner cannot cancel or renew current owner`() {
        val m = mailbox()
        m.send(1, 0)
        assertEquals(ContinuousTouchMailbox.Admission.WRONG_OWNER, m.send(2, 1, owner = "other_owner"))
        assertFalse(m.isRetired())
        assertEquals(1, m.size())
        assertTrue(m.expired(2501))
    }

    @Test fun `capture epoch mismatch duplicate or wrong gesture immediately fence owner`() {
        for (mode in 0..2) {
            val m = mailbox()
            m.send(1, 0)
            val result = when (mode) {
                0 -> m.send(2, 2, epoch = "other_epoch")
                1 -> m.send(1, 2)
                else -> m.send(2, 2, gesture = 2)
            }
            assertEquals(ContinuousTouchMailbox.Admission.INVALID, result)
            assertTrue(m.isRetired())
            assertEquals(0, m.size())
        }
    }

    @Test fun `heartbeat cannot rejuvenate an already stale pending down`() {
        val m = mailbox()
        m.send(1, 0)
        m.send(2, 4, at = 1490)
        assertNull(m.poll(1501))
        assertTrue(m.isRetired())
    }

    @Test fun `adjacent heartbeats are coalesced without synthetic movement`() {
        val m = mailbox()
        m.send(1, 4, gesture = 0)
        assertEquals(ContinuousTouchMailbox.Admission.COALESCED, m.send(2, 4, gesture = 0))
        assertEquals(1, m.size())
        assertEquals(4, m.poll(1100)!!.action)
    }

    @Test fun `receipt clock regression and expired lease reject without dispatch`() {
        for (at in listOf(999L, 2500L)) {
            val m = mailbox()
            assertEquals(ContinuousTouchMailbox.Admission.INVALID, m.send(1, 0, at = at))
            assertTrue(m.isRetired())
        }
    }

    @Test fun `poll clock regression retires and never returns pending input`() {
        val m = mailbox()
        m.send(1, 0)
        assertNull(m.poll(1000))
        assertTrue(m.isRetired())
    }

    @Test fun `wrong bounds event type and gesture cannot acquire touch`() {
        for (sample in listOf(TouchSample(1,1,0,-1,0,1001), TouchSample(1,1,0,960,0,1001),
            TouchSample(1,1,0,0,540,1001),TouchSample(1,1,5,0,0,1001),TouchSample(1,0,0,0,0,1001))) {
            val m = mailbox()
            assertEquals(ContinuousTouchMailbox.Admission.INVALID, m.offer(binding.owner,binding.captureEpoch,sample))
            assertEquals(0,m.size())
        }
    }

    @Test fun `malformed ownership and geometry rejected before process creation`() {
        for (owner in listOf("", "tiny", "a\nbcdefgh", "a bcdefgh", "x".repeat(129))) {
            assertThrows(IllegalArgumentException::class.java) { binding.copy(owner = owner) }
        }
        assertThrows(IllegalArgumentException::class.java) { binding.copy(width = 0) }
        assertThrows(IllegalArgumentException::class.java) { binding.copy(height = 16385) }
        assertThrows(IllegalArgumentException::class.java) { binding.copy(rotation = 4) }
    }
}
