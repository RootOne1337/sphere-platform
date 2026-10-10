package com.sphereplatform.agent.commands

import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.StreamingManager
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicLong

class ContinuousInputControllerTest {
    private class Fixture(enabled: Boolean = true, private val holdStartup: Boolean = false) {
        val job = SupervisorJob()
        val scope = CoroutineScope(job + Dispatchers.Unconfined)
        val now = AtomicLong(100)
        @Volatile var connection: Long? = 1
        @Volatile var capture: CaptureInputSession? = CaptureInputSession("epoch_1234", 960, 540, 1280, 720, 0)
        @Volatile var outbound = true
        @Volatile var opens = 0
        @Volatile var closed = false
        val entered = CompletableDeferred<Unit>(); val release = CompletableDeferred<Unit>()
        val receipts = CopyOnWriteArrayList<JsonObject>()
        val samples = CopyOnWriteArrayList<TouchSample>()
        val streaming = mockk<StreamingManager>()
        init { every { streaming.getInputSession() } answers { capture } }
        val controller = ContinuousInputController(scope, TouchPipeFactory {
            opens++; entered.complete(Unit)
            if (holdStartup) release.await()
            object : TouchPipe {
                override suspend fun send(sample: TouchSample): RootTouchWire.Ack {
                    samples.add(sample)
                    return java.io.ByteArrayOutputStream().let {
                        RootTouchWire.ack(it, sample.sequence, when (sample.action) { 4 -> 2; 3 -> 3; else -> 1 }, now.get())
                        RootTouchWire.readAck(java.io.ByteArrayInputStream(it.toByteArray()))
                    }
                }
                override suspend fun closeAndConfirm(): Boolean { closed = true; return true }
            }
        }, streaming, { connection }, { expected, message ->
            if (outbound && connection == expected) { receipts.add(message); true } else false
        }, now::get, enabled)

        fun open(owner: String = "owner_1234", epoch: String = "epoch_1234", width: Int = 1280) = buildJsonObject {
            put("type", "continuous_input_open"); put("owner", owner); put("session_id", "viewer_1234")
            put("capture_epoch", epoch); put("frame_width", width); put("frame_height", 720)
        }
        fun event(sequence: Int, action: Int, x: Int = 400, y: Int = 200, owner: String = "owner_1234", epoch: String = "epoch_1234") = buildJsonObject {
            put("type", "continuous_input_event"); put("owner", owner); put("capture_epoch", epoch)
            put("sequence", sequence); put("gesture", if (action == 4) 0 else 1)
            put("action", action); put("x", x); put("y", y)
        }
        suspend fun ready() {
            controller.handle(open())
            eventually { receipts.any { it["stage"]?.jsonPrimitive?.content == "startup" && it["status"]?.jsonPrimitive?.int == 0 } }
        }
        suspend fun stop() { controller.invalidate(); if (opens != 0) eventually { closed }; job.cancelAndJoin() }
    }

    @Test fun `default build is silent and never accesses capture or root`() = runBlocking {
        val f = Fixture(false)
        assertTrue(f.controller.handle(f.open()))
        assertTrue(f.controller.handle(buildJsonObject { put("type", "continuous_input_probe"); put("session_id", "viewer_1234") }))
        assertTrue(f.controller.handle(f.event(1, 0)))
        assertFalse(f.controller.handle(buildJsonObject { put("type", "touch_tap") }))
        assertEquals(0, f.opens); assertTrue(f.receipts.isEmpty())
        verify(exactly = 0) { f.streaming.getInputSession() }
        f.stop()
    }

    @Test fun `probe reports a capture offer without claiming native readiness`() = runBlocking {
        val f = Fixture()
        f.controller.handle(buildJsonObject { put("type", "continuous_input_probe"); put("session_id", "viewer_1234") })
        val offer = f.receipts.single()
        assertEquals("continuous_input_offer", offer["type"]!!.jsonPrimitive.content)
        assertFalse(offer["injector_ready"]!!.jsonPrimitive.boolean)
        assertEquals(1280, offer["frame_width"]!!.jsonPrimitive.int)
        assertEquals(960, offer["physical_width"]!!.jsonPrimitive.int)
        assertEquals(0, f.opens)
        f.stop()
    }

    @Test fun `old epoch frame size or malformed identity never starts a helper`() = runBlocking {
        val f = Fixture()
        for (message in listOf(f.open(epoch = "older_5678"), f.open(width = 960), f.open(owner = "short"),
            JsonObject(f.open() + ("frame_width" to JsonPrimitive("1280"))), JsonObject(f.open() + ("extra" to JsonPrimitive(true))))) {
            f.controller.handle(message)
        }
        assertEquals(0, f.opens)
        f.stop()
    }

    @Test fun `movement is mapped to physical pixels and delivered before terminal event`() = runBlocking {
        val f = Fixture(); f.ready()
        f.controller.handle(f.event(1, 0))
        eventually { f.samples.size == 1 }
        f.controller.handle(f.event(2, 2, 800, 400))
        eventually { f.samples.size == 2 }
        assertEquals(listOf(0, 2), f.samples.map { it.action })
        assertEquals(listOf(300, 600), f.samples.map { it.x })
        assertEquals(listOf(150, 300), f.samples.map { it.y })
        f.controller.handle(f.event(3, 1, 800, 400))
        eventually { f.samples.size == 3 }
        assertEquals(1, f.samples.last().action)
        f.stop()
    }

    @Test fun `foreign owner cannot inject cancel or replace a legitimate owner`() = runBlocking {
        val f = Fixture(); f.ready()
        f.controller.handle(f.event(1, 0, owner = "foreign_5678"))
        f.controller.handle(buildJsonObject { put("type", "continuous_input_close"); put("owner", "foreign_5678") })
        f.controller.handle(f.open(owner = "foreign_5678"))
        assertFalse(f.closed); assertTrue(f.samples.isEmpty()); assertEquals(1, f.opens)
        f.controller.handle(f.event(1, 0))
        eventually { f.samples.size == 1 }
        f.stop()
    }

    @Test fun `same-size capture replacement releases old touch instead of retargeting it`() = runBlocking {
        val f = Fixture(); f.ready()
        f.controller.handle(f.event(1, 0)); eventually { f.samples.size == 1 }
        f.capture = f.capture!!.copy(epoch = "epoch_5678")
        f.controller.handle(f.event(2, 2))
        eventually { f.closed }
        assertEquals(1, f.samples.size)
        f.stop()
    }

    @Test fun `owner malformed sequence action coordinates and metadata fail closed without coercion`() = runBlocking {
        for ((key, value) in listOf("sequence" to JsonPrimitive("2"), "action" to JsonPrimitive(5),
            "x" to JsonPrimitive(-1), "x" to JsonPrimitive(1280), "gesture" to JsonPrimitive(true), "extra" to JsonPrimitive(1))) {
            val f = Fixture(); f.ready()
            f.controller.handle(f.event(1, 0)); eventually { f.samples.size == 1 }
            f.controller.handle(JsonObject(f.event(2, 2) + (key to value)))
            eventually { f.closed }
            assertEquals(1, f.samples.size)
            assertTrue(f.receipts.any { it["origin"]?.jsonPrimitive?.content == "admission" && it["status"]?.jsonPrimitive?.int == 5 })
            f.stop()
        }
    }

    @Test fun `replacement WebSocket generation gets neither old input nor old receipts`() = runBlocking {
        val f = Fixture(); f.ready()
        f.controller.handle(f.event(1, 0)); eventually { f.samples.size == 1 }
        eventually { f.receipts.any { it["stage"]?.jsonPrimitive?.content == "input" && it["sequence"]?.jsonPrimitive?.int == 1 } }
        val count = f.receipts.size
        f.connection = 2
        f.controller.handle(f.event(2, 2))
        eventually { f.closed }
        assertEquals(1, f.samples.size); assertEquals(count, f.receipts.size)
        f.stop()
    }

    @Test fun `capture invalidated while root starts cannot emit readiness or inject afterward`() = runBlocking {
        val f = Fixture(holdStartup = true)
        f.controller.handle(f.open()); f.entered.await()
        f.controller.invalidate(); f.release.complete(Unit)
        eventually { f.closed }
        assertTrue(f.samples.isEmpty())
        assertFalse(f.receipts.any { it["stage"]?.jsonPrimitive?.content == "startup" && it["status"]?.jsonPrimitive?.int == 0 })
        f.stop()
    }

    @Test fun `DOWN before native readiness is refused without pending injection`() = runBlocking {
        val f = Fixture(holdStartup = true)
        f.controller.handle(f.open()); f.entered.await()
        f.controller.handle(f.event(1, 0)); f.release.complete(Unit)
        eventually { f.closed }
        assertTrue(f.samples.isEmpty())
        f.stop()
    }

    @Test fun `unavailable outbound ACK retires local input without reconnect replay`() = runBlocking {
        val f = Fixture(); f.ready(); f.outbound = false
        f.controller.handle(f.event(1, 0))
        eventually { f.closed }
        assertEquals(1, f.samples.size)
        f.controller.handle(f.event(2, 2))
        assertEquals(1, f.samples.size)
        f.stop()
    }

    @Test fun `inactivity expires locally even when other owners send heartbeats`() = runBlocking {
        val f = Fixture(); f.ready()
        f.controller.handle(f.event(1, 0)); eventually { f.samples.size == 1 }
        f.now.set(1600)
        f.controller.handle(f.event(2, 4, owner = "foreign_5678"))
        eventually { f.closed }
        assertEquals(1, f.samples.size)
        f.stop()
    }

    companion object {
        private suspend fun eventually(check: () -> Boolean) = withTimeout(3_000) {
            while (!check()) delay(5)
        }
    }
}
