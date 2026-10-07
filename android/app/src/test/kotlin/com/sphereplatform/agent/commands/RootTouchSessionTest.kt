package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test
import java.io.*

class RootTouchSessionTest {
    private data class Event(val action: Int, val x: Int, val y: Int, val down: Long, val at: Long)
    private class Fixture {
        val events = mutableListOf<Event>()
        var geometry = true
        var rejectAction = -1
        var throwAction = -1
        val state = RootTouchSession(960, 540, 1000, { action, x, y, down, at ->
            events.add(Event(action, x, y, down, at))
            if (action == throwAction) throw IOException("fixture private content")
            action != rejectAction
        }, { geometry })
        fun send(seq: Int, action: Int, at: Long = 1000L + seq, gesture: Long = 1, x: Int = 100, y: Int = 100) =
            state.apply(seq, gesture, action, x, y, at)
    }

    @Test fun `move is injected while held before up and uses device monotonic down time`() {
        val f = Fixture()
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.send(1, RootTouchSession.DOWN))
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.send(2, RootTouchSession.MOVE, x = 220))
        assertTrue(f.state.isHeld)
        assertEquals(listOf(0, 2), f.events.map { it.action })
        assertEquals(220, f.events.last().x)
        f.send(3, RootTouchSession.UP)
        assertFalse(f.state.isHeld)
        assertEquals(listOf(0, 2, 1), f.events.map { it.action })
        assertTrue(f.events.all { it.down == 1001L })
    }

    @Test fun `idle owner is retired without injecting anything`() {
        val f = Fixture()
        assertEquals(RootTouchSession.Result.EXPIRED, f.state.tick(2500))
        assertTrue(f.state.isClosed)
        assertTrue(f.events.isEmpty())
    }

    @Test fun `held network loss cancels locally at lease expiry and stale packets cannot revive it`() {
        val f = Fixture()
        f.send(1, RootTouchSession.DOWN)
        assertNull(f.state.tick(2500))
        assertEquals(RootTouchSession.Result.EXPIRED, f.state.tick(2501))
        assertEquals(listOf(0, 3), f.events.map { it.action })
        assertEquals(RootTouchSession.Result.REJECTED, f.send(2, RootTouchSession.MOVE, 2502))
        assertEquals(2, f.events.size)
    }

    @Test fun `valid heartbeat holds without synthesizing movement`() {
        val f = Fixture()
        f.send(1, RootTouchSession.DOWN)
        assertEquals(RootTouchSession.Result.HEARTBEAT_ACCEPTED, f.send(2, RootTouchSession.HEARTBEAT, 2200))
        assertNull(f.state.tick(3600))
        assertEquals(1, f.events.size)
        assertEquals(RootTouchSession.Result.EXPIRED, f.state.tick(3700))
    }

    @Test fun `idle heartbeat uses zero gesture and cannot introduce touch`() {
        val f = Fixture()
        assertEquals(RootTouchSession.Result.HEARTBEAT_ACCEPTED, f.send(1, RootTouchSession.HEARTBEAT, gesture = 0))
        assertTrue(f.events.isEmpty())
        assertFalse(f.state.isHeld)
    }

    @Test fun `duplicate and reordered event retire gesture rather than replay it`() {
        for (seq in listOf(0, 1, -1)) {
            val f = Fixture()
            f.send(1, RootTouchSession.DOWN)
            assertEquals(RootTouchSession.Result.REJECTED, f.send(seq, RootTouchSession.MOVE))
            assertEquals(listOf(0, 3), f.events.map { it.action })
            assertTrue(f.state.isClosed)
        }
    }

    @Test fun `coalesced move sequence gap is accepted without replaying missing points`() {
        val f = Fixture()
        f.send(1, RootTouchSession.DOWN)
        assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.send(12, RootTouchSession.MOVE))
        assertEquals(listOf(0, 2), f.events.map { it.action })
    }

    @Test fun `wrong gesture cannot move or release another held gesture`() {
        for (action in listOf(1, 2, 3, 4)) {
            val f = Fixture()
            f.send(1, RootTouchSession.DOWN)
            assertEquals(RootTouchSession.Result.REJECTED, f.send(2, action, gesture = 2))
            assertEquals(listOf(0, 3), f.events.map { it.action })
        }
    }

    @Test fun `second down cannot silently replace held finger`() {
        val f = Fixture()
        f.send(1, RootTouchSession.DOWN)
        assertEquals(RootTouchSession.Result.REJECTED, f.send(2, RootTouchSession.DOWN, gesture = 2))
        assertEquals(listOf(0, 3), f.events.map { it.action })
    }

    @Test fun `new gesture needs increasing id after up or cancel`() {
        for (terminal in listOf(1, 3)) {
            val f = Fixture()
            f.send(1, RootTouchSession.DOWN)
            f.send(2, terminal)
            assertEquals(RootTouchSession.Result.DISPATCHER_ACCEPTED, f.send(3, RootTouchSession.DOWN, gesture = 2))
            f.send(4, RootTouchSession.UP, gesture = 2)
            assertEquals(RootTouchSession.Result.REJECTED, f.send(5, RootTouchSession.DOWN, gesture = 2))
            assertEquals(4, f.events.size)
        }
    }

    @Test fun `all frame boundaries rejected before injection`() {
        for (point in listOf(-1 to 0, 960 to 0, 0 to -1, 0 to 540, Int.MAX_VALUE to 100)) {
            val f = Fixture()
            assertEquals(RootTouchSession.Result.REJECTED, f.send(1, 0, x = point.first, y = point.second))
            assertTrue(f.events.isEmpty())
        }
    }

    @Test fun `geometry change cancels even without new input`() {
        val f = Fixture()
        f.send(1, RootTouchSession.DOWN)
        f.geometry = false
        assertEquals(RootTouchSession.Result.REJECTED, f.state.tick(1100))
        assertEquals(listOf(0, 3), f.events.map { it.action })
        assertTrue(f.state.isClosed)
    }

    @Test fun `unknown down move and up all attempt cancel without retry`() {
        for (action in listOf(0, 1, 2)) for (throwing in listOf(false, true)) {
            val f = Fixture()
            if (action != 0) f.send(1, 0)
            if (throwing) f.throwAction = action else f.rejectAction = action
            assertEquals(RootTouchSession.Result.UNKNOWN, f.send(if (action == 0) 1 else 2, action))
            assertEquals(1, f.events.count { it.action == action })
            assertEquals(3, f.events.last().action)
            assertTrue(f.state.isClosed)
        }
    }

    @Test fun `failed cancellation remains unknown and never enables new input`() {
        val f = Fixture()
        f.send(1, 0)
        f.rejectAction = 3
        assertEquals(RootTouchSession.Result.UNKNOWN, f.send(2, 3))
        assertTrue(f.state.isClosed)
        assertEquals(RootTouchSession.Result.REJECTED, f.send(3, 0, gesture = 2))
        assertEquals(listOf(0, 3), f.events.map { it.action })
    }

    @Test fun `EOF cleanup cancels once and is idempotent`() {
        val f = Fixture()
        f.send(1, 0)
        assertEquals(RootTouchSession.Result.CANCELLED, f.state.close(1100))
        f.state.close(1200)
        assertEquals(listOf(0, 3), f.events.map { it.action })
    }

    @Test fun `clock regression cancels with nonregressing Android event time`() {
        val f = Fixture()
        f.send(1, 0, 1100)
        assertEquals(RootTouchSession.Result.REJECTED, f.state.tick(1099))
        assertEquals(1100L, f.events.last().at)
    }

    @Test fun `fixed size wire preserves long gesture and sequence and truncation fails`() {
        val bytes = ByteArrayOutputStream()
        RootTouchWire.write(DataOutputStream(bytes), RootTouchWire.Packet(23, Long.MAX_VALUE, 2, 959, 539))
        assertEquals(RootTouchWire.INPUT_LINE_BYTES, bytes.size())
        val packet = RootTouchWire.read(DataInputStream(ByteArrayInputStream(bytes.toByteArray())))
        assertEquals(23, packet.sequence)
        assertEquals(Long.MAX_VALUE, packet.gesture)
        assertEquals(959, packet.x)
        assertEquals(539, packet.y)
        for (length in 0 until bytes.size()) {
            assertThrows(IOException::class.java) {
                RootTouchWire.read(DataInputStream(ByteArrayInputStream(bytes.toByteArray().copyOf(length))))
            }
        }
    }

    @Test fun `wrong protocol magic rejected and acknowledgement has constant size`() {
        assertThrows(IOException::class.java) {
            RootTouchWire.read(DataInputStream(ByteArrayInputStream(ByteArray(25))))
        }
        val bytes = ByteArrayOutputStream()
        RootTouchWire.ack(DataOutputStream(bytes), 1, 2, 3500)
        assertEquals(RootTouchWire.ACK_LINE_BYTES, bytes.size())
    }

    @Test fun `su newline conversion preserves every packet byte including LF and CR`() {
        val bytes = ByteArrayOutputStream()
        RootTouchWire.write(bytes, RootTouchWire.Packet(10, 13, 2, 10, 13))
        val crlf = bytes.toString("US-ASCII").replace("\n", "\r\n").toByteArray()
        val packet = RootTouchWire.read(ByteArrayInputStream(crlf))
        assertEquals(10, packet.sequence)
        assertEquals(13L, packet.gesture)
        assertEquals(10, packet.x)
        assertEquals(13, packet.y)
        val ackBytes = ByteArrayOutputStream()
        RootTouchWire.ack(ackBytes, 10, 2, 13)
        val ack = RootTouchWire.readAck(ByteArrayInputStream(ackBytes.toString("US-ASCII").replace("\n", "\r\n").toByteArray()))
        assertEquals(10, ack.sequence)
        assertEquals(2, ack.status)
        assertEquals(13L, ack.uptimeMs)
    }

    @Test fun `extra digit invalid character and bad line ending are bounded and rejected`() {
        val bytes = ByteArrayOutputStream()
        RootTouchWire.write(bytes, RootTouchWire.Packet(1, 1, 0, 10, 20))
        val line = bytes.toString("US-ASCII")
        for (bad in listOf("g" + line.drop(1), line.dropLast(1) + "0\n", line.dropLast(1) + "\r\r\n", "\n" + line)) {
            assertThrows(IOException::class.java) { RootTouchWire.read(ByteArrayInputStream(bad.toByteArray())) }
        }
    }

    @Test fun `v1 acknowledgement status numbers are explicit rather than enum ordinals`() {
        assertEquals(1, RootTouchSession.Result.DISPATCHER_ACCEPTED.wireCode)
        assertEquals(2, RootTouchSession.Result.HEARTBEAT_ACCEPTED.wireCode)
        assertEquals(3, RootTouchSession.Result.CANCELLED.wireCode)
        assertEquals(4, RootTouchSession.Result.EXPIRED.wireCode)
        assertEquals(5, RootTouchSession.Result.REJECTED.wireCode)
        assertEquals(6, RootTouchSession.Result.UNKNOWN.wireCode)
    }

    @Test fun `geometry failure retires even idle owner and does not renew lease`() {
        val events = mutableListOf<Int>()
        val state = RootTouchSession(960, 540, 1000, { action, _, _, _, _ -> events.add(action); true },
            { throw IOException("private platform detail") })
        assertEquals(RootTouchSession.Result.UNKNOWN, state.apply(1, 0, 4, 0, 0, 1100))
        assertTrue(state.isClosed)
        assertTrue(events.isEmpty())
    }

    @Test fun `invalid configuration and event enum cannot acquire a pointer`() {
        assertThrows(IllegalArgumentException::class.java) { RootTouchSession(0, 540, 1000, { _, _, _, _, _ -> true }, { true }) }
        for (action in listOf(-1, 5, 255)) {
            val f = Fixture()
            assertEquals(RootTouchSession.Result.REJECTED, f.send(1, action))
            assertTrue(f.events.isEmpty())
        }
    }
}
