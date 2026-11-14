package com.sphereplatform.agent.commands

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException

class TimedPointerPathTest {
    private fun path(vararg points: Triple<Long, Int, Int>) = TimedPointerPath.parse(buildJsonObject {
        put("schema_version", 1); put("frame_width", 960); put("frame_height", 540)
        put("points", buildJsonArray { points.forEachIndexed { i, p -> add(buildJsonObject {
            put("t_ms", p.first); put("action", when(i) { 0 -> 0; points.lastIndex -> 1; else -> 2 })
            put("x", p.second); put("y", p.third)
        }) } })
    })
    private class Fixture(retain: Boolean = false) {
        var now = 1000L; var closed = false; var fenced = false; var current = true
        var opens = 0; var closes = 0
        var ackDelay = 0L; var reject = false; var writeFails = false; var cleanup = true
        val injected = mutableListOf<List<Long>>()
        val samples = mutableListOf<TouchSample>()
        val session = RootTouchSession(1920, 1080, now, { a, x, y, down, at ->
            injected.add(listOf(a.toLong(), x.toLong(), y.toLong(), down, at)); true
        }, { current })
        val pipe = object : TouchPipe {
            override suspend fun send(sample: TouchSample): RootTouchWire.Ack {
                samples.add(sample)
                val result = session.apply(sample.sequence, sample.gesture, sample.action, sample.x, sample.y, now)
                if (writeFails) throw IOException("private process error")
                now += ackDelay
                val out = ByteArrayOutputStream()
                RootTouchWire.ack(out, sample.sequence, if (reject) 6 else result.wireCode, now)
                return RootTouchWire.readAck(ByteArrayInputStream(out.toByteArray()))
            }
            override suspend fun closeAndConfirm(): Boolean {
                closes++; closed = true; session.close(now); return cleanup
            }
        }
        val player = TimedPointerPathPlayer(TouchPipeFactory { opens++; pipe }, { now }, { now += it }, { fenced = true }, retain)
        val binding = TouchBinding("task_owner_1234", "task_epoch_1234", 1920, 1080, 0)
        suspend fun play(path: TimedPointerPath, checkpoint: suspend () -> Unit = {}) = player.play(path, binding, { current }, checkpoint)
    }

    @Test fun `slow path preserves holds reversals and one native down time`() = runBlocking {
        val f = Fixture()
        val result = f.play(path(Triple(0,100,200), Triple(2000,200,200), Triple(4000,100,300), Triple(5500,100,300)))
        assertEquals(listOf(0L,2L,2L,1L), f.injected.map { it[0] })
        assertEquals(listOf(1000L,3000L,5000L,6500L), f.injected.map { it[4] })
        assertTrue(f.injected.all { it[3] == 1000L })
        assertTrue(f.samples.count { it.action == 4 } >= 15)
        assertEquals(4, result.points); assertEquals(5500L, result.durationMs)
        assertEquals(0L, result.maxScheduleLatenessMs); assertTrue(f.closed); assertFalse(f.fenced)
        assertFalse(f.session.isHeld)
    }
    @Test fun `native ACK delay does not accumulate into the absolute schedule`() = runBlocking {
        val f = Fixture(); f.ackDelay = 12
        f.play(path(Triple(0,1,2), Triple(100,2,3), Triple(200,3,4), Triple(300,4,5)))
        assertEquals(listOf(1000L,1100L,1200L,1300L), f.injected.map { it[4] })
    }
    @Test fun `two gestures and their gap share one helper and planned timeline despite ACK and bookkeeping`() = runBlocking {
        val f = Fixture(retain = true); f.ackDelay = 12
        val first = f.play(path(Triple(0,1,2), Triple(100,2,3)))
        assertFalse(f.closed); assertFalse(first.helperReused)
        f.now += 17 // DAG logging and progress after the native UP ACK.
        assertTrue(f.player.gap(400, { f.current }) {})
        f.now += 11 // Bookkeeping after the gap does not rebase the second path.
        val second = f.play(path(Triple(0,3,4), Triple(100,4,5)))
        assertEquals(listOf(1000L,1100L,1511L,1600L), f.injected.map { it[4] })
        assertEquals(listOf(1000L,1000L,1511L,1511L), f.injected.map { it[3] })
        assertEquals(500L, second.timelineOffsetMs); assertEquals(11L, second.startLatenessMs)
        assertTrue(second.helperReused); assertEquals(1, f.opens); assertEquals(0, f.closes)
        val touch = f.samples.filter { it.action != RootTouchSession.HEARTBEAT }
        assertEquals(listOf(1L,1L,2L,2L), touch.map { it.gesture })
        assertTrue(f.samples.zipWithNext().all { (a,b) -> b.sequence > a.sequence })
        f.player.close(); f.player.close(); assertEquals(1, f.closes); assertFalse(f.session.isHeld)
    }
    @Test fun `long idle gap maintains lease without injecting extra motion`() = runBlocking {
        val f = Fixture(retain = true)
        f.play(path(Triple(0,1,2), Triple(100,2,3)))
        assertTrue(f.player.gap(5000, { f.current }) {})
        val second = f.play(path(Triple(0,3,4), Triple(100,4,5)))
        assertEquals(listOf(1000L,1100L,6100L,6200L), f.injected.map { it[4] })
        assertEquals(5100L, second.timelineOffsetMs)
        assertTrue(f.samples.count { it.action == RootTouchSession.HEARTBEAT && it.gesture == 0L } >= 15)
        assertEquals(1, f.opens); f.player.close()
    }
    @Test fun `cancel in an idle gap closes before propagation and never emits next DOWN`() = runBlocking {
        val f = Fixture(retain = true)
        f.play(path(Triple(0,1,2), Triple(100,2,3)))
        try { f.player.gap(5000, { f.current }) { if (f.now >= 1400) throw CancellationException("test_cancel") }; fail() }
        catch (_: CancellationException) {}
        assertEquals(listOf(0L,1L), f.injected.map { it[0] }); assertTrue(f.closed)
        assertFalse(f.player.gap(1, { f.current }) {}); assertEquals(1, f.opens)
    }
    @Test fun `overdue next gesture terminates timeline without a catch up DOWN`() = runBlocking {
        val f = Fixture(retain = true)
        f.play(path(Triple(0,1,2), Triple(100,2,3))); f.now += 250
        try { f.play(path(Triple(0,3,4), Triple(100,4,5))); fail() }
        catch (e: PointerPathInterruptedException) { assertEquals(0, e.attemptedPoints) }
        assertEquals(listOf(0L,1L), f.injected.map { it[0] }); assertTrue(f.closed)
    }
    @Test fun `geometry change between paths closes retained helper without replay`() = runBlocking {
        val f = Fixture(retain = true)
        f.play(path(Triple(0,1,2), Triple(100,2,3))); f.current = false
        try { f.play(path(Triple(0,3,4), Triple(100,4,5))); fail() }
        catch (_: PointerPathInterruptedException) {}
        assertTrue(f.closed); assertEquals(1, f.opens); assertEquals(2, f.injected.size)
    }
    @Test fun `unknown retained helper cleanup fences at explicit task boundary`() = runBlocking {
        val f = Fixture(retain = true)
        f.play(path(Triple(0,1,2), Triple(100,2,3))); f.cleanup = false
        try { f.player.close(); fail() } catch (_: PointerPathInterruptedException) {}
        assertTrue(f.fenced); assertEquals(1, f.closes)
    }
    @Test fun `missed schedule never produces a burst of stale moves`() = runBlocking {
        val f = Fixture(); f.ackDelay = 220
        try { f.play(path(Triple(0,1,2), Triple(10,2,3), Triple(20,3,4))); fail() }
        catch (e: PointerPathInterruptedException) { assertEquals(1,e.attemptedPoints) }
        assertEquals(listOf(0L,3L), f.injected.map { it[0] }); assertTrue(f.closed)
    }
    @Test fun `cancellation while holding releases before propagating and never resumes`() = runBlocking {
        val f = Fixture()
        try { f.play(path(Triple(0,1,2), Triple(5000,2,3))) {
            if (f.now >= 1200) throw CancellationException("test_cancel")
        }; fail() } catch (_: CancellationException) {}
        assertEquals(listOf(0L,3L), f.injected.map { it[0] }); assertFalse(f.session.isHeld)
    }
    @Test fun `partial write is non replayable even with confirmed final cleanup`() = runBlocking {
        val f = Fixture(); f.writeFails = true
        try { f.play(path(Triple(0,1,2), Triple(100,2,3))); fail() }
        catch (e: RootCommandOutcomeUnknownException) { assertTrue(e is PointerPathInterruptedException) }
        assertTrue(f.closed); assertFalse(f.fenced)
    }
    @Test fun `unknown cleanup fences the entire device`() = runBlocking {
        val f = Fixture(); f.cleanup = false
        try { f.play(path(Triple(0,1,2), Triple(100,2,3))); fail() }
        catch (_: PointerPathInterruptedException) {}
        assertTrue(f.fenced)
    }
    @Test fun `changed geometry interrupts and releases rather than remapping a held finger`() = runBlocking {
        val f = Fixture()
        try { f.play(path(Triple(0,1,2), Triple(1000,2,3))) { if (f.now >= 1200) f.current = false }; fail() }
        catch (_: PointerPathInterruptedException) {}
        assertTrue(f.closed); assertFalse(f.session.isHeld)
    }
    @Test fun `parser rejects malformed order time bounds versions and unknown keys before root`() {
        val valid = path(Triple(0,1,2), Triple(100,2,3))
        assertEquals(100L, valid.durationMs)
        val base = """{"schema_version":1,"frame_width":960,"frame_height":540,"points":[{"t_ms":0,"action":0,"x":1,"y":2},{"t_ms":100,"action":1,"x":2,"y":3}]}"""
        for (raw in listOf(base.replace("\"schema_version\":1", "\"schema_version\":2"),
            base.replace("\"t_ms\":100", "\"t_ms\":60001"), base.replace("\"t_ms\":0", "\"t_ms\":1"),
            base.replace("\"x\":2", "\"x\":960"), base.replace("\"action\":1", "\"action\":2"),
            base.replace("\"frame_width\":960", "\"frame_width\":960.0"),
            base.replace("\"y\":3", "\"y\":3,\"secret\":1"))) {
            assertThrows(IllegalArgumentException::class.java) { TimedPointerPath.parse(Json.parseToJsonElement(raw).jsonObject) }
        }
    }
}
