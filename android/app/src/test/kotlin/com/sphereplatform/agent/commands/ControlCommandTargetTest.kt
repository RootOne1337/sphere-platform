package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.ws.SphereWebSocketClient
import io.mockk.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Real dispatcher, journal and DAG runner; only OS/network/storage are replaced. */
@OptIn(ExperimentalCoroutinesApi::class)
class ControlCommandTargetTest {
    private val ws = mockk<SphereWebSocketClient>(relaxed = true)
    private val adb = mockk<AdbActionExecutor>(relaxed = true)
    private val callback = slot<((JsonObject) -> Unit)?>()
    private val messages = mutableListOf<JsonObject>()
    private val oldId = "11111111-1111-4111-8111-111111111111"
    private val currentId = "22222222-2222-4222-8222-222222222222"

    private fun start(scope: kotlinx.coroutines.CoroutineScope): CommandDispatcher {
        val prefs = mockk<EncryptedSharedPreferences>(relaxed = true)
        val editor = mockk<android.content.SharedPreferences.Editor>(relaxed = true)
        val disk = mutableMapOf<String, String?>()
        every { prefs.getString(any(), any()) } answers { disk[firstArg()] }
        every { prefs.edit() } returns editor
        every { editor.putString(any(), any()) } answers { disk[firstArg()] = secondArg(); editor }
        every { editor.commit() } returns true
        every { ws.onJsonMessage = captureNullable(callback) } just Runs
        every { ws.sendJson(capture(messages)) } returns true
        val runner = DagRunner(mockk(relaxed = true), adb, ws, prefs, mockk(relaxed = true))
        return CommandDispatcher(ws, adb, runner, mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), scope, mockk(relaxed = true), mockk(relaxed = true), CommandJournal(prefs))
            .also { it.start() }
    }

    private fun execute(id: String) = buildJsonObject {
        put("type", "EXECUTE_DAG"); put("command_id", id)
        put("signed_at", System.currentTimeMillis() / 1000)
        put("payload", buildJsonObject { put("dag", buildJsonObject {
            put("entry_node", "wait")
            put("nodes", buildJsonArray {
                add(buildJsonObject {
                    put("id", "wait"); put("on_success", "tap")
                    put("action", buildJsonObject { put("type", "sleep"); put("ms", 100) })
                })
                add(buildJsonObject {
                    put("id", "tap")
                    put("action", buildJsonObject { put("type", "tap"); put("x", 10); put("y", 20) })
                })
            })
        }) })
    }

    private fun control(type: String, target: JsonElement? = JsonPrimitive(currentId)) = buildJsonObject {
        put("type", type); put("command_id", "control_${type}_test")
        put("signed_at", System.currentTimeMillis() / 1000)
        if (target != null) put("payload", buildJsonObject { put("task_id", target) })
    }

    private fun send(message: JsonObject) { callback.captured!!(message) }
    private fun terminal(id: String) = messages.lastOrNull {
        it["command_id"]?.jsonPrimitive?.content == id &&
            it["status"]?.jsonPrimitive?.content in listOf("completed", "failed")
    }

    @Test fun delayedCancelForCompletedTaskCannotStopNextTask() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(oldId)); runCurrent(); advanceTimeBy(150); runCurrent()
        assertEquals("completed", terminal(oldId)?.get("status")?.jsonPrimitive?.content)
        clearMocks(adb, answers = false)
        send(execute(currentId)); runCurrent()
        send(control("CANCEL_DAG", JsonPrimitive(oldId))); runCurrent()
        advanceTimeBy(150); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        assertEquals("completed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun cancelForCurrentTaskStopsBeforeNextAction() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent()
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun missingOrMalformedTargetCannotCancelCurrentTask() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent()
        for (target in listOf(null, JsonNull, JsonPrimitive(""), JsonPrimitive(" "),
            JsonPrimitive(123), buildJsonObject { put("unexpected", true) })) {
            send(control("CANCEL_DAG", target)); runCurrent()
            assertEquals("failed", messages.last()["status"]?.jsonPrimitive?.content)
            assertEquals("invalid_task_target", messages.last()["error"]?.jsonPrimitive?.content)
        }
        advanceTimeBy(150); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        dispatcher.stop()
    }

    @Test fun latePauseCannotSuspendAnotherTask() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent()
        send(control("PAUSE_DAG", JsonPrimitive(oldId))); runCurrent()
        advanceTimeBy(150); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        assertEquals("completed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun lateResumeCannotReleaseAnotherTasksPause() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent()
        send(control("PAUSE_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        send(control("RESUME_DAG", JsonPrimitive(oldId))); runCurrent()
        advanceTimeBy(250); runCurrent()
        verify(exactly = 0) { adb.tap(any(), any()) }
        send(control("RESUME_DAG")); runCurrent(); advanceTimeBy(250); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        dispatcher.stop()
    }

    @Test fun controlsAfterCompletionCannotClaimAnActiveExecution() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent(); advanceTimeBy(150); runCurrent()
        for (type in listOf("CANCEL_DAG", "PAUSE_DAG", "RESUME_DAG")) {
            send(control(type)); runCurrent()
            assertEquals("failed", messages.last()["status"]?.jsonPrimitive?.content)
            assertEquals("task_not_running", messages.last()["error"]?.jsonPrimitive?.content)
        }
        dispatcher.stop()
    }

    @Test fun invalidDagDoesNotLeaveAnActiveControlTarget() = runTest {
        val dispatcher = start(backgroundScope)
        send(JsonObject(execute(currentId) + ("payload" to buildJsonObject { put("dag", buildJsonObject {}) })))
        runCurrent()
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        send(control("CANCEL_DAG")); runCurrent()
        assertEquals("task_not_running", messages.last()["error"]?.jsonPrimitive?.content)
        send(execute(oldId)); runCurrent(); advanceTimeBy(150); runCurrent()
        assertEquals("completed", terminal(oldId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }
}
