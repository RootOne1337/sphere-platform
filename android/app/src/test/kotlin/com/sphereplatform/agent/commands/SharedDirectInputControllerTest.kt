package com.sphereplatform.agent.commands

import com.sphereplatform.agent.direct.DirectInputChannel
import com.sphereplatform.agent.streaming.CaptureInputSession
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class SharedDirectInputControllerTest {
    private class Fixture {
        val now = AtomicLong(1000)
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val capture = CaptureInputSession("00112233-4455-6677-8899-aabbccddeeff", 960, 540, 960, 540, 0)
        val packets = CopyOnWriteArrayList<TouchSample>()
        val opened = AtomicInteger()
        val closed = AtomicInteger()
        val keys = CopyOnWriteArrayList<Pair<Int, Int>>()
        var unknownCancel = false
        var processingMs = 0L
        var startupCleanupUnknown = false
        var refusedOpens = 0
        var refusalDetail = TouchStartupDetail.ROOT_INPUT_BUSY
        val controller = SharedDirectInputController(scope, TouchPipeFactory {
            opened.incrementAndGet()
            if (startupCleanupUnknown) throw TouchPipeCleanupUnknownException(TouchStartupDetail.ROOT_READY_TIMEOUT)
            if (refusedOpens > 0) { refusedOpens--; throw TouchStartupUnavailableException(refusalDetail) }
            val native = RootTouchSession(960, 540, now.get(), { action, _, _, _, _ ->
                !(unknownCancel && action == RootTouchSession.CANCEL)
            }, { true }, { action, code, _, _, _ -> keys += action to code; true })
            object : TouchPipe {
                override suspend fun send(sample: TouchSample): RootTouchWire.Ack {
                    packets += sample
                    now.addAndGet(processingMs)
                    val result = native.apply(sample.sequence, sample.gesture, sample.action, sample.x, sample.y, now.get())
                    val bytes = ByteArrayOutputStream()
                    RootTouchWire.ack(bytes, sample.sequence, result.wireCode, now.get())
                    return RootTouchWire.readAck(ByteArrayInputStream(bytes.toByteArray()))
                }
                override suspend fun closeAndConfirm(): Boolean {
                    closed.incrementAndGet(); native.close(now.get())
                    return native.cleanupExitCode() == 0
                }
            }
        }, { capture }, now::get)
        inner class Peer(val id: String) : DirectInputChannel {
            override val session = id
            override val capture = this@Fixture.capture
            @Volatile var current = true
            val messages = CopyOnWriteArrayList<JsonObject>()
            var onMessage: ((JsonObject) -> Unit)? = null
            override fun isCurrent() = current
            override fun send(message: JsonObject): Boolean { if (current) { messages += message; onMessage?.invoke(message) }; return current }
            fun outcomes() = messages.mapNotNull { it["outcome"]?.jsonPrimitive?.content }
            fun event(sequence: Int, action: Int, gesture: Long = 1) = controller.message(id, buildJsonObject {
                put("type", "touch_event"); put("sequence", sequence); put("gesture", gesture)
                put("action", action); put("x", 20); put("y", 30)
            })
            fun open() = controller.message(id, buildJsonObject {
                put("type", "touch_open"); put("capture_epoch", capture.epoch)
                put("frame_width", 960); put("frame_height", 540)
            })
            fun key(sequence: Int, code: Int) = controller.message(id, buildJsonObject {
                put("type", "key_event"); put("sequence", sequence); put("keycode", code)
            })
        }
        suspend fun peer(n: Int): Peer = Peer(n.toString(16).padStart(32, '0')).also {
            assertTrue(controller.grant(it)); assertTrue(it.open())
            eventually { "ready" in it.outcomes() }
        }
        fun finish() = scope.cancel()
    }

    @Test fun `no authenticated peer grant means no native process or input`() = runBlocking {
        val f = Fixture()
        try {
            val peer = f.Peer("a".repeat(32))
            assertFalse(peer.open()); assertFalse(peer.event(1, 0))
            assertEquals(0, f.opened.get()); assertTrue(f.packets.isEmpty())
        } finally { f.finish() }
    }

    @Test fun `unconfirmed startup cleanup retains the original phase without granting fresh input`() = runBlocking {
        val f = Fixture(); f.startupCleanupUnknown = true
        try {
            val peer = f.Peer("a".repeat(32))
            assertTrue(f.controller.grant(peer)); assertTrue(peer.open())
            eventually { f.controller.diagnosticSnapshot()?.get("state") == JsonPrimitive("cleanup_unknown") }
            val snapshot = checkNotNull(f.controller.diagnosticSnapshot())
            assertEquals(JsonPrimitive("root_ready_timeout"), snapshot["last_startup_detail"])
            assertEquals(JsonPrimitive(1L), snapshot["startup_failures_total"])
            assertEquals(JsonPrimitive(0L), snapshot["startups_total"])
            assertTrue(f.packets.isEmpty())
            assertFalse("ready" in peer.outcomes())
            assertFalse("closed" in peer.outcomes())
            val another = f.Peer("b".repeat(32))
            assertTrue(f.controller.grant(another)); assertTrue(another.open())
            eventually { "unknown" in another.outcomes() }
            assertFalse("ready" in another.outcomes())
            assertFalse("denied" in another.outcomes())
            assertFalse("closed" in another.outcomes())
            assertTrue(f.packets.isEmpty())
        } finally { f.finish() }
    }

    @Test fun `proven pre input root timeout closes only the refused participant and fresh admission works`() = runBlocking {
        val f = Fixture(); f.refusedOpens = 1; f.refusalDetail = TouchStartupDetail.ROOT_READY_TIMEOUT
        try {
            val cold = f.Peer("a".repeat(32))
            assertTrue(f.controller.grant(cold)); assertTrue(cold.open())
            eventually { "closed" in cold.outcomes() }
            assertTrue("denied" in cold.outcomes()); assertFalse("unknown" in cold.outcomes())
            assertFalse("ready" in cold.outcomes()); assertTrue(f.packets.isEmpty())
            val fresh = f.peer(2)
            assertTrue(fresh.event(1, RootTouchSession.DOWN))
            eventually { "applied" in fresh.outcomes() }
            assertTrue(fresh.event(2, RootTouchSession.UP))
            eventually { fresh.outcomes().count { it == "applied" } == 2 }
            assertEquals(2, f.opened.get())
        } finally { f.finish() }
    }

    @Test fun `native dispatch time is sampled while idle heartbeat cannot dilute actions`() = runBlocking {
        val f = Fixture()
        try {
            val peer = f.peer(1)
            f.processingMs = 60
            assertTrue(peer.event(1, RootTouchSession.DOWN))
            eventually { peer.outcomes().count { it == "applied" } == 1 }
            val measured = checkNotNull(f.controller.diagnosticSnapshot())["shared_input_timing"]!!.jsonObject
            assertEquals(JsonPrimitive(60L), measured["processing_ms_last"])
            assertEquals(JsonPrimitive(1), measured["window_samples"])
            f.processingMs = 0
            assertTrue(peer.event(2, RootTouchSession.HEARTBEAT))
            eventually { peer.messages.any { it["sequence"] == JsonPrimitive(2) } }
            val idle = checkNotNull(f.controller.diagnosticSnapshot())["shared_input_timing"]!!.jsonObject
            assertEquals(JsonPrimitive(1), idle["window_samples"])
            assertEquals(JsonPrimitive(60L), idle["processing_ms_max"])
        } finally { f.finish() }
    }

    @Test fun `known startup refusal ends its participant before an immediate same-peer OPEN`() = runBlocking {
        val f=Fixture();f.refusedOpens=1
        try {
            val peer=f.Peer("a".repeat(32));var reopened=false
            peer.onMessage={message -> if (!reopened && message["outcome"]==JsonPrimitive("closed")) {
                reopened=true;assertTrue(peer.open())
            }}
            assertTrue(f.controller.grant(peer));assertTrue(peer.open())
            eventually { "ready" in peer.outcomes() }
            assertEquals(listOf("denied","closed","ready"),peer.outcomes().filter{it!="alive"})
            assertEquals(2,f.opened.get());assertEquals(0,f.closed.get())
        } finally {f.finish()}
    }

    @Test fun `ten peers share one native pipe and every peer can click`() = runBlocking {
        val f = Fixture()
        try {
            val peers = (1..10).map { f.peer(it) }
            assertFalse(f.controller.grant(f.Peer("b".repeat(32))))
            for (peer in peers) {
                assertTrue(peer.event(1, 0)); eventually { peer.outcomes().count { it == "applied" } == 1 }
                assertTrue(peer.event(2, 1)); eventually { peer.outcomes().count { it == "applied" } == 2 }
            }
            assertEquals(1, f.opened.get())
            assertEquals(20, f.packets.count { it.action != 4 })
            assertEquals(10, f.packets.filter { it.action == 0 }.map { it.gesture }.toSet().size)
        } finally { f.finish() }
    }

    @Test fun `takeover cancels native finger without closing either participant or replaying old move`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            a.event(1, 0); eventually { "applied" in a.outcomes() }
            b.event(1, 0); eventually { "interrupted" in a.outcomes() && "applied" in b.outcomes() }
            a.event(2, 2); a.event(3, 1)
            eventually { a.outcomes().count { it == "interrupted" } == 3 }
            assertEquals(listOf(0, 3, 0), f.packets.filter { it.action != 4 }.map { it.action })
            assertEquals(0, f.closed.get()); assertEquals(1, f.opened.get())
            a.event(4, 0, 2); eventually { a.outcomes().count { it == "applied" } == 2 }
            assertEquals(listOf(0, 3, 0, 3, 0), f.packets.filter { it.action != 4 }.map { it.action })
        } finally { f.finish() }
    }

    @Test fun `closing an idle participant cannot cancel another participants gesture`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            b.event(1, 0); eventually { "applied" in b.outcomes() }
            assertTrue(f.controller.message(a.id, buildJsonObject { put("type", "touch_close") }))
            eventually { "closed" in a.outcomes() }
            assertEquals(listOf(0), f.packets.filter { it.action != 4 }.map { it.action })
            assertEquals(0, f.closed.get())
            b.event(2, 1); eventually { b.outcomes().count { it == "applied" } == 2 }
        } finally { f.finish() }
    }

    @Test fun `peer loss cancels only its held gesture while the other peer stays usable`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            a.event(1, 0); eventually { "applied" in a.outcomes() }
            a.current = false; f.controller.closed(a.id)
            eventually { f.packets.any { it.action == 3 } }
            b.event(1, 0); eventually { "applied" in b.outcomes() }
            assertEquals(listOf(0, 3, 0), f.packets.filter { it.action != 4 }.map { it.action })
            assertEquals(1, f.opened.get())
        } finally { f.finish() }
    }

    @Test fun `unknown native CANCEL cannot acknowledge the new DOWN or open a second pipe`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            a.event(1, 0); eventually { "applied" in a.outcomes() }
            f.unknownCancel = true
            b.event(1, 0); eventually { "unknown" in b.outcomes() }
            assertFalse("applied" in b.outcomes())
            assertEquals(listOf(0, 3), f.packets.filter { it.action != 4 }.map { it.action })
            // Transport admission is independent of native execution: video
            // stays available, while the uncertain injector still rejects OPEN.
            val watcher = f.Peer("c".repeat(32))
            assertTrue(f.controller.grant(watcher)); assertTrue(watcher.open())
            eventually { "unknown" in watcher.outcomes() }
            assertFalse("ready" in watcher.outcomes())
            assertFalse("denied" in watcher.outcomes())
            assertFalse("closed" in watcher.outcomes())
            assertEquals(1, f.opened.get())
        } finally { f.finish() }
    }

    @Test fun `system keys use the existing shared pipe and interrupt only the held gesture`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            a.event(1, 0); eventually { "applied" in a.outcomes() }
            assertTrue(b.key(1, 3))
            eventually { "applied" in b.outcomes() && "interrupted" in a.outcomes() }
            assertEquals(listOf(0, 3, 5), f.packets.filter { it.action != 4 }.map { it.action })
            assertEquals(listOf(0 to 3, 1 to 3), f.keys.toList())
            assertEquals(1, f.opened.get()); assertEquals(0, f.closed.get())
            a.event(2, 1); eventually { a.outcomes().count { it == "interrupted" } == 2 }
            assertTrue(a.key(3, 4)); eventually { a.outcomes().count { it == "applied" } == 2 }
            assertEquals(listOf(0 to 3, 1 to 3, 0 to 4, 1 to 4), f.keys.toList())
            assertEquals(0, f.closed.get())
        } finally { f.finish() }
    }

    @Test fun `duplicate key and forbidden power key never replay or execute on a foreign participant`() = runBlocking {
        val f = Fixture()
        try {
            val a = f.peer(1); val b = f.peer(2)
            a.key(1, 187); eventually { "applied" in a.outcomes() }
            a.key(1, 187); eventually { "closed" in a.outcomes() }
            b.key(1, 26); eventually { "closed" in b.outcomes() }
            assertEquals(listOf(0 to 187, 1 to 187), f.keys.toList())
        } finally { f.finish() }
    }

    private companion object {
        suspend fun eventually(predicate: () -> Boolean) = withTimeout(2500) {
            while (!predicate()) delay(5)
        }
    }
}
