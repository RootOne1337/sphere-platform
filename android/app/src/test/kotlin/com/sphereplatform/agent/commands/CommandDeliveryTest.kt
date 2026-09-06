package com.sphereplatform.agent.commands

import com.sphereplatform.agent.ws.SphereWebSocketClient
import io.mockk.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Exercise the production dispatcher through its WebSocket callback. */
@OptIn(ExperimentalCoroutinesApi::class)
class CommandDeliveryTest {
    private val ws = mockk<SphereWebSocketClient>(relaxed = true)
    private val dag = mockk<DagRunner>(relaxed = true)
    private val cache = mockk<ScriptCacheManager>(relaxed = true)
    private val messages = mutableListOf<JsonObject>()
    private val callback = slot<((JsonObject) -> Unit)?>()
    private val disk = mutableMapOf<String, String?>()
    private fun journal(): CommandJournal {
        val prefs = mockk<androidx.security.crypto.EncryptedSharedPreferences>(relaxed = true)
        val editor = mockk<android.content.SharedPreferences.Editor>(relaxed = true)
        every { prefs.getString(any(), any()) } answers { disk[firstArg()] }
        every { prefs.edit() } returns editor
        every { editor.putString(any(), any()) } answers {
            disk[firstArg()] = secondArg(); editor
        }
        every { editor.commit() } returns true
        return CommandJournal(prefs)
    }

    private fun dispatcher(scope: kotlinx.coroutines.CoroutineScope): CommandDispatcher {
        every { ws.onJsonMessage = captureNullable(callback) } just Runs
        every { ws.sendJson(capture(messages)) } returns true
        return CommandDispatcher(ws, mockk(relaxed = true), dag, cache,
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), scope, mockk(relaxed = true), mockk(relaxed = true), journal())
            .also { it.start() }
    }

    private fun command() = buildJsonObject {
        put("type", "EXECUTE_DAG")
        put("command_id", "11111111-1111-4111-8111-111111111111")
        put("signed_at", System.currentTimeMillis() / 1000)
        put("payload", buildJsonObject { put("dag", buildJsonObject { put("fixture", true) }) })
    }

    @Test fun failedDagIsReportedAsFailed() = runTest {
        coEvery { dag.execute(any(), any(), any()) } returns buildJsonObject { put("success", false) }
        val dispatcher = dispatcher(backgroundScope)
        callback.captured!!(command())
        runCurrent()
        assertEquals("failed", messages.last()["status"]?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun duplicateActiveDagDoesNotCancelOrExecuteAgain() = runTest {
        val finish = CompletableDeferred<JsonObject>()
        coEvery { dag.execute(any(), any(), any()) } coAnswers { finish.await() }
        val dispatcher = dispatcher(backgroundScope)
        callback.captured!!(command())
        runCurrent()
        callback.captured!!(command())
        runCurrent()
        verify(exactly = 0) { dag.requestCancel() }
        finish.complete(buildJsonObject { put("success", true) })
        runCurrent()
        coVerify(exactly = 1) { dag.execute(any(), any(), any()) }
        dispatcher.stop()
    }

    @Test fun duplicateCompletedDagReplaysResultWithoutExecution() = runTest {
        coEvery { dag.execute(any(), any(), any()) } returns buildJsonObject { put("success", true) }
        val dispatcher = dispatcher(backgroundScope)
        repeat(2) { callback.captured!!(command()); runCurrent() }
        coVerify(exactly = 1) { dag.execute(any(), any(), any()) }
        assertEquals("completed", messages.last()["status"]?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun disconnectedTerminalResultSurvivesDispatcherRestart() = runTest {
        coEvery { dag.execute(any(), any(), any()) } returns buildJsonObject { put("success", false) }
        val dispatcher = dispatcher(backgroundScope)
        every { ws.sendJson(any()) } returns false
        callback.captured!!(command())
        runCurrent()
        val pending = journal().pending().single()
        assertEquals("failed", pending["status"]!!.jsonPrimitive.content)
        dispatcher.stop()
    }
}
