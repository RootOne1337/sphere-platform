package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.workers.UpdateCheckScheduler
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
    private val streaming = mockk<com.sphereplatform.agent.streaming.StreamingManager>(relaxed = true)
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
        val journal = CommandJournal(prefs, ReceiptStoreFixture().store)
        val runner = DagRunner(mockk(relaxed = true), adb, ws, journal, mockk(relaxed = true))
        return CommandDispatcher(ws, adb, runner, mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), scope, streaming, mockk(relaxed = true), journal,
            mockk<UpdateCheckScheduler>(relaxed = true))
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
    private val qualityId = "interactive_12345678-1234-4234-8234-123456789abc"
    private fun quality(action: String, settings: JsonObject? = null, age: Long = 0) = buildJsonObject {
        put("type", "stream_quality"); put("command_id", qualityId)
        put("signed_at", System.currentTimeMillis() / 1000 - age); put("ttl_seconds", 15)
        put("payload", buildJsonObject { put("action", action); settings?.let { put("settings", it) } })
    }

    @Test fun qualityWriteAcknowledgesTheActualManagerSnapshotWithoutTouchOrCaptureCommands() = runTest {
        val settings = com.sphereplatform.agent.streaming.StreamQualitySettings("detail", 60, 12_000_000)
        every { streaming.configureStreamQuality(settings) } returns
            com.sphereplatform.agent.streaming.StreamQualitySnapshot(true, settings = settings)
        val dispatcher = start(backgroundScope)
        send(quality("set", buildJsonObject { put("profile", "detail"); put("max_fps", 60); put("max_bitrate_bps", 12_000_000) }))
        runCurrent()
        assertEquals("completed", terminal(qualityId)!!["status"]!!.jsonPrimitive.content)
        assertEquals("detail", terminal(qualityId)!!["result"]!!.jsonObject["settings"]!!.jsonObject["profile"]!!.jsonPrimitive.content)
        verify(exactly = 1) { streaming.configureStreamQuality(settings) }
        verify(exactly = 0) { streaming.stop() }
        dispatcher.stop()
    }

    @Test fun expiredOrInvalidQualityCannotReachTheSharedEncoder() = runTest {
        val dispatcher = start(backgroundScope)
        send(quality("set", buildJsonObject { put("max_fps", 60) }, age = 60)); runCurrent()
        assertEquals("expired", terminal(qualityId)!!["error"]!!.jsonPrimitive.content)
        send(quality("set", buildJsonObject { put("max_fps", 61) })); runCurrent()
        assertEquals("stream_quality_invalid", terminal(qualityId)!!["error"]!!.jsonPrimitive.content)
        verify(exactly = 0) { streaming.configureStreamQuality(any()) }
        dispatcher.stop()
    }

    @Test fun qualityReadDoesNotWritePreferencesAndCodecRefusalIsNotCompleted() = runTest {
        every { streaming.getStreamQuality() } returns com.sphereplatform.agent.streaming.StreamQualitySnapshot(
            true, settings = com.sphereplatform.agent.streaming.StreamQualitySettings())
        every { streaming.configureStreamQuality(any()) } throws IllegalStateException("stream_quality_codec_refused")
        val dispatcher = start(backgroundScope)
        send(quality("get")); runCurrent()
        assertEquals("completed", terminal(qualityId)!!["status"]!!.jsonPrimitive.content)
        verify(exactly = 0) { streaming.configureStreamQuality(any()) }
        send(quality("set", buildJsonObject { put("profile", "detail") })); runCurrent()
        assertEquals("failed", terminal(qualityId)!!["status"]!!.jsonPrimitive.content)
        assertEquals("stream_quality_codec_refused", terminal(qualityId)!!["error"]!!.jsonPrimitive.content)
        dispatcher.stop()
    }
    private fun durableCancel(target: String = currentId) = JsonObject(control("CANCEL_DAG") +
        ("payload" to buildJsonObject { put("task_id", target); put("durable", true) }))

    @Test fun durableCancelBeforeExecutePreventsAllDeviceActions() = runTest {
        val dispatcher = start(backgroundScope)
        send(durableCancel()); runCurrent()
        val cancelled = terminal(currentId)
        assertTrue(cancelled!!["result"]!!.jsonObject["cancelled"]!!.jsonPrimitive.boolean)
        repeat(3) { send(execute(currentId)); runCurrent(); advanceTimeBy(150); runCurrent() }
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertEquals(cancelled, terminal(currentId))
        dispatcher.stop()
    }

    @Test fun durableCancelAcceptancePrecedesActualTerminalReceipt() = runTest {
        val dispatcher = start(backgroundScope)
        send(execute(currentId)); runCurrent()
        send(durableCancel()); runCurrent()
        assertNull(terminal(currentId)) // Still inside the sleep action.
        assertEquals("completed", terminal("control_CANCEL_DAG_test")!!["status"]!!.jsonPrimitive.content)
        advanceTimeBy(150); runCurrent()
        assertTrue(terminal(currentId)!!["result"]!!.jsonObject["cancelled"]!!.jsonPrimitive.boolean)
        verify(exactly = 0) { adb.tap(any(), any()) }
        dispatcher.stop()
    }
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

    private fun loopCommand(nested: Boolean = false): JsonObject {
        fun node(id: String, action: JsonObject) = buildJsonObject { put("id", id); put("action", action) }
        val body = buildJsonArray {
            add(node("wait", buildJsonObject { put("type", "sleep"); put("ms", 100) }))
            add(node("tap", buildJsonObject { put("type", "tap"); put("x", 10); put("y", 20) }))
        }
        val loop = buildJsonObject { put("type", "loop"); put("count", 1); put("body", body) }
        val action = if (nested) buildJsonObject {
            put("type", "loop"); put("count", 1)
            put("body", buildJsonArray { add(node("inner", loop)) })
        } else loop
        return withDag(buildJsonObject {
            put("entry_node", "repeat")
            put("nodes", buildJsonArray { add(node("repeat", action)) })
        })
    }

    private fun withDag(dag: JsonObject) = JsonObject(execute(currentId) +
        ("payload" to buildJsonObject { put("dag", dag) }))

    @Test fun wireCancelStopsBeforeTheNextLoopBodyActionAndPersistsFailure() = runTest {
        val dispatcher = start(backgroundScope)
        send(loopCommand()); runCurrent()
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        assertEquals("completed", terminal("control_CANCEL_DAG_test")?.get("status")?.jsonPrimitive?.content)
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        val original = terminal(currentId)
        send(loopCommand()); runCurrent(); advanceTimeBy(150); runCurrent()
        assertEquals(original, terminal(currentId)) // Durable terminal replay, no rerun.
        verify(exactly = 0) { adb.tap(any(), any()) }
        dispatcher.stop()
    }

    @Test fun wireCancelEscapesNestedLoopBodies() = runTest {
        val dispatcher = start(backgroundScope)
        send(loopCommand(nested = true)); runCurrent()
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun wirePauseStopsInsideLoopUntilMatchingResume() = runTest {
        val dispatcher = start(backgroundScope)
        send(loopCommand()); runCurrent()
        send(control("PAUSE_DAG")); runCurrent(); advanceTimeBy(350); runCurrent()
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertNull(terminal(currentId))
        send(control("RESUME_DAG")); runCurrent(); advanceTimeBy(250); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        assertEquals("completed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun wireCancelReleasesAPausedLoopWithoutResumingActions() = runTest {
        val dispatcher = start(backgroundScope)
        send(loopCommand()); runCurrent()
        send(control("PAUSE_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(250); runCurrent()
        verify(exactly = 0) { adb.tap(any(), any()) }
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun cancellationDuringFinalActionCannotReturnSuccessfulDag() = runTest {
        val dispatcher = start(backgroundScope)
        send(withDag(buildJsonObject {
            put("entry_node", "wait")
            put("nodes", buildJsonArray { add(buildJsonObject {
                put("id", "wait")
                put("action", buildJsonObject { put("type", "sleep"); put("ms", 100) })
            }) })
        })); runCurrent()
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(150); runCurrent()
        assertEquals("completed", terminal("control_CANCEL_DAG_test")?.get("status")?.jsonPrimitive?.content)
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }

    @Test fun cancellationDuringRetryBackoffCannotSendAnotherDeviceAction() = runTest {
        val dispatcher = start(backgroundScope)
        var calls = 0
        every { adb.tap(10, 20) } answers {
            calls++
            if (calls == 1) throw IllegalStateException("isolated retryable failure")
        }
        send(withDag(buildJsonObject {
            put("entry_node", "tap")
            put("nodes", buildJsonArray { add(buildJsonObject {
                put("id", "tap"); put("retry", 1)
                put("action", buildJsonObject { put("type", "tap"); put("x", 10); put("y", 20) })
            }) })
        })); runCurrent() // First failure is now in the 50 ms retry backoff.
        send(control("CANCEL_DAG")); runCurrent(); advanceTimeBy(100); runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        assertEquals("failed", terminal(currentId)?.get("status")?.jsonPrimitive?.content)
        dispatcher.stop()
    }
}
