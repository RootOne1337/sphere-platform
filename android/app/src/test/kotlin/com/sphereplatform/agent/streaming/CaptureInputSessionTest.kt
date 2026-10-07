package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Test

class CaptureInputSessionTest {
    private val geometry = CaptureInputGeometry(960, 540, 1280, 720, 0)

    @Test fun `same-size capture restart creates a new identity and fences the previous frame`() {
        val first = CaptureInputSession.create(geometry)
        val second = CaptureInputSession.create(geometry)
        assertNotEquals(first.epoch, second.epoch)
        assertNull(second.map(first.epoch, 1280, 720, StreamPoint(400, 200)))
        assertEquals(StreamPoint(300, 150), second.map(second.epoch, 1280, 720, StreamPoint(400, 200)))
    }

    @Test fun `same-size 180-degree rotation is not the displayed capture`() {
        val session = CaptureInputSession.create(geometry)
        assertTrue(session.matchesDisplay(960, 540, 0))
        assertFalse(session.matchesDisplay(960, 540, 2))
        assertFalse(session.matchesDisplay(540, 960, 1))
        assertFalse(session.matchesDisplay(1280, 720, 0))
    }

    @Test fun `frame bounds and dimensions are part of admission rather than clamped input`() {
        val session = CaptureInputSession.create(geometry)
        assertNull(session.map(session.epoch, 960, 540, StreamPoint(400, 200)))
        assertNull(session.map(session.epoch, 1280, 720, StreamPoint(-1, 0)))
        assertNull(session.map(session.epoch, 1280, 720, StreamPoint(1280, 1)))
        assertEquals(StreamPoint(959, 539), session.map(session.epoch, 1280, 720, StreamPoint(1279, 719)))
    }

    @Test fun `portrait native pixels are preserved and invalid session identifiers are refused`() {
        val session = CaptureInputSession.create(CaptureInputGeometry(540, 960, 540, 960, 1))
        assertEquals(StreamPoint(539, 959), session.map(session.epoch, 540, 960, StreamPoint(539, 959)))
        assertThrows(IllegalArgumentException::class.java) { CaptureInputSession("short", 960, 540, 960, 540, 0) }
        assertThrows(IllegalArgumentException::class.java) { CaptureInputSession("epoch_1234", 0, 540, 960, 540, 0) }
        assertThrows(IllegalArgumentException::class.java) { CaptureInputSession("epoch_1234", 960, 540, 960, 540, 4) }
    }
}
