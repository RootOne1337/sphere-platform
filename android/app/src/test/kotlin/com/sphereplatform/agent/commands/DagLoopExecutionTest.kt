package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.lua.LuaEngine
import com.sphereplatform.agent.ws.SphereWebSocketClient
import io.mockk.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Execute actual loop nodes; diagnostic limits must not change device actions. */
@OptIn(ExperimentalCoroutinesApi::class)
class DagLoopExecutionTest {
    private val adb = mockk<AdbActionExecutor>(relaxed = true)
    private val ws = mockk<SphereWebSocketClient>(relaxed = true)
    private val prefs = mockk<EncryptedSharedPreferences>(relaxed = true)
    private val lua = mockk<LuaEngine>(relaxed = true)
    private val runner = DagRunner(lua, adb, ws, prefs, mockk(relaxed = true))

    private fun bodyNode(id: String, type: String, abort: Boolean = false, fields: JsonObjectBuilder.() -> Unit = {}) =
        buildJsonObject {
            put("id", id); put("abort_on_failure", abort)
            put("action", buildJsonObject { put("type", type); fields() })
        }

    private fun loop(count: Int, vararg body: JsonObject, inspectResult: Boolean = false) = buildJsonObject {
        put("entry_node", "repeat")
        put("nodes", buildJsonArray { add(buildJsonObject {
            put("id", "repeat")
            if (inspectResult) put("on_success", "inspect")
            put("action", buildJsonObject {
                put("type", "loop"); put("count", count); put("max_iterations", count)
                put("body", buildJsonArray { body.forEach { add(it) } })
            })
        })
            if (inspectResult) add(bodyNode("inspect", "lua") { put("code", "inspect-loop-result") })
        })
    }

    @Test fun diagnosticLimitCannotSkipRemainingActions() = runTest {
        val result = runner.execute("long-loop", loop(75,
            bodyNode("a", "tap") { put("x", 1); put("y", 1) },
            bodyNode("b", "tap") { put("x", 2); put("y", 2) },
            bodyNode("c", "tap") { put("x", 3); put("y", 3) },
        ))
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
        verify(exactly = 75) { adb.tap(1, 1) }
        verify(exactly = 75) { adb.tap(2, 2) }
        verify(exactly = 75) { adb.tap(3, 3) }
    }

    @Test fun failureAfterDiagnosticLimitStillStopsAnAbortingLoop() = runTest {
        var calls = 0
        every { adb.keyEvent(4) } answers {
            calls++
            if (calls == 201) throw IllegalStateException("isolated action failure after log cap")
        }
        val failure = runCatching {
            runner.execute("failing-long-loop", loop(205, bodyNode("key", "key_event", abort = true) { put("keycode", 4) }))
        }.exceptionOrNull()
        assertEquals(201, calls)
        assertNotNull("Action failure must not be replaced by a successful truncated loop", failure)
        assertTrue(failure!!.message!!.contains("isolated action failure"))
    }

    @Test fun coroutineCancellationDoesNotRunTheNextLoopAction() = runTest {
        val job = launch {
            runner.execute("cancelled-loop", loop(2,
                bodyNode("wait", "sleep") { put("ms", 10_000) },
                bodyNode("tap", "tap") { put("x", 9); put("y", 9) },
            ))
        }
        runCurrent() // The first loop action is suspended in delay.
        job.cancelAndJoin()
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertFalse(runner.requestCancel("cancelled-loop")) // Active identity was cleared.
    }

    @Test fun diagnosticsStayBoundedWithoutAllocatingAnUnboundedLoopResult() = runTest {
        val context = slot<Map<String, Any?>>()
        coEvery { lua.execute(any(), capture(context)) } returns null
        runner.execute("bounded-loop", loop(500, bodyNode("key", "key_event") { put("keycode", 4) }, inspectResult = true))
        verify(exactly = 500) { adb.keyEvent(4) }
        val loopResult = context.captured["repeat"] as Map<*, *>
        assertEquals(500, loopResult["iterations"])
        assertEquals(200, (loopResult["logs"] as List<*>).size)
        assertEquals(true, loopResult["logs_truncated"])
    }

    @Test fun exactLogCapacityIsNotReportedAsTruncation() = runTest {
        val context = slot<Map<String, Any?>>()
        coEvery { lua.execute(any(), capture(context)) } returns null
        runner.execute("exact-cap-loop", loop(200, bodyNode("key", "key_event") { put("keycode", 4) }, inspectResult = true))
        val loopResult = context.captured["repeat"] as Map<*, *>
        assertEquals(200, (loopResult["logs"] as List<*>).size)
        assertEquals(false, loopResult["logs_truncated"])
    }
}
