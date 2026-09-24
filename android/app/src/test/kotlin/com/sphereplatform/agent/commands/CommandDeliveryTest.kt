package com.sphereplatform.agent.commands

import android.content.Context
import android.content.Intent
import com.sphereplatform.agent.streaming.StreamQualityMonitor
import com.sphereplatform.agent.streaming.StreamingManager
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.ws.SphereWebSocketClient
import io.mockk.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import timber.log.Timber

/** Exercise the production dispatcher through its WebSocket callback. */
@OptIn(ExperimentalCoroutinesApi::class)
class CommandDeliveryTest {
    private val ws = mockk<SphereWebSocketClient>(relaxed = true)
    private val dag = mockk<DagRunner>(relaxed = true)
    private val cache = mockk<ScriptCacheManager>(relaxed = true)
    private val adb = mockk<AdbActionExecutor>(relaxed = true)
    private val messages = mutableListOf<JsonObject>()
    private val callback = slot<((JsonObject) -> Unit)?>()
    private val appContext = mockk<Context>(relaxed = true)
    private val disk = mutableMapOf<String, String?>()
    private val receipts = ReceiptStoreFixture()
    private fun journal(): CommandJournal {
        val prefs = mockk<androidx.security.crypto.EncryptedSharedPreferences>(relaxed = true)
        val editor = mockk<android.content.SharedPreferences.Editor>(relaxed = true)
        every { prefs.getString(any(), any()) } answers { disk[firstArg()] }
        every { prefs.edit() } returns editor
        every { editor.putString(any(), any()) } answers {
            disk[firstArg()] = secondArg(); editor
        }
        every { editor.commit() } returns true
        return CommandJournal(prefs, receipts.store)
    }

    private fun mockIntentFlags() {
        mockkConstructor(Intent::class)
        every { anyConstructed<Intent>().addFlags(any()) } answers { self as Intent }
    }

    private fun dispatcher(
        scope: kotlinx.coroutines.CoroutineScope,
        streamingManager: StreamingManager = mockk(relaxed = true),
        authStore: AuthTokenStore = mockk(relaxed = true),
        context: Context = appContext,
        otaService: OtaUpdateService = mockk(relaxed = true),
    ): CommandDispatcher {
        every { ws.onJsonMessage = captureNullable(callback) } just Runs
        every { ws.sendJson(capture(messages)) } returns true
        return CommandDispatcher(ws, adb, dag, cache,
            mockk(relaxed = true), mockk(relaxed = true), authStore,
            otaService, mockk(relaxed = true), mockk(relaxed = true),
            mockk(relaxed = true), scope, streamingManager, context, journal())
            .also { it.start() }
    }

    @Test fun discoveredRouteUpdateKeepsFallbackAndReconnectsAfterAcknowledgement() = runTest {
        val authStore = mockk<AuthTokenStore>(relaxed = true)
        every { authStore.connectionRoutesSnapshot() } returnsMany listOf(
            AuthTokenStore.ConnectionRoutes(1, listOf("https://cloudflare.invalid")),
            AuthTokenStore.ConnectionRoutes(2, listOf("https://alternate.invalid", "https://cloudflare.invalid")),
        )
        val dispatcher = dispatcher(backgroundScope, authStore = authStore)
        val update = buildJsonObject {
            put("type", "UPDATE_CONFIG")
            put("command_id", "22222222-2222-4222-8222-222222222222")
            put("signed_at", System.currentTimeMillis() / 1000)
            put("ttl_seconds", 60)
            put("payload", buildJsonObject {
                put("server_url", "https://alternate.invalid")
                put("fallback_server_url", "https://cloudflare.invalid")
            })
        }

        callback.captured!!(update)
        runCurrent()

        verify(exactly = 1) {
            authStore.saveServerRoutes("https://alternate.invalid", "https://cloudflare.invalid")
        }
        verify(exactly = 0) { authStore.saveServerUrl(any()) }
        assertEquals("completed", messages.last()["status"]?.jsonPrimitive?.content)
        verify(exactly = 0) { ws.forceReconnectNow(any()) }

        advanceTimeBy(750)
        runCurrent()
        verifyOrder {
            ws.sendJson(match { it["status"]?.jsonPrimitive?.content == "completed" })
            ws.forceReconnectNow(bypassDebounce = true)
        }
        dispatcher.stop()
    }

    @Test fun unchangedRouteUpdateDoesNotDisconnectHealthySession() = runTest {
        val authStore = mockk<AuthTokenStore>(relaxed = true)
        val currentRoutes = AuthTokenStore.ConnectionRoutes(4, listOf("https://primary.invalid"))
        every { authStore.connectionRoutesSnapshot() } returnsMany listOf(currentRoutes, currentRoutes)
        val dispatcher = dispatcher(backgroundScope, authStore = authStore)
        val update = buildJsonObject {
            put("type", "UPDATE_CONFIG")
            put("command_id", "33333333-3333-4333-8333-333333333333")
            put("signed_at", System.currentTimeMillis() / 1000)
            put("ttl_seconds", 60)
            put("payload", buildJsonObject { put("server_url", "https://primary.invalid") })
        }

        callback.captured!!(update)
        runCurrent()
        advanceTimeBy(1_000)
        runCurrent()

        verify(exactly = 1) { authStore.saveServerUrl("https://primary.invalid") }
        verify(exactly = 0) { ws.forceReconnectNow(any()) }
        dispatcher.stop()
    }

    @Test fun activeStreamStatsAreIncludedInHeartbeatPong() = runTest {
        val streaming = mockk<StreamingManager>(relaxed = true)
        every { streaming.isActive() } returns true
        every { streaming.getQualityStats() } returns StreamQualityMonitor.StreamStats(
            currentFps = 17,
            totalFrames = 88,
            totalEncodedBytes = 456_789L,
            keyFrameRatio = 0.125f,
            avgEncodedFrameSizeKb = 5.2f,
            webSocketQueueAttemptsTotal = 30,
            webSocketQueueAcceptedTotal = 29,
            webSocketQueueRejectedTotal = 1,
            webSocketQueueAcceptedBytesTotal = 450_000,
        )

        val dispatcher = dispatcher(backgroundScope, streaming)
        callback.captured!!(buildJsonObject { put("type", "ping"); put("ts", 123.0) })

        val stream = messages.last()["stream"]?.jsonObject
        assertNotNull("active capture telemetry must reach backend", stream)
        assertEquals(1, stream!!["schema_version"]?.jsonPrimitive?.int)
        assertEquals(17, stream["encoder_fps"]?.jsonPrimitive?.int)
        assertEquals(88L, stream["encoded_frames_total"]?.jsonPrimitive?.long)
        assertEquals(456_789L, stream["encoded_bytes_total"]?.jsonPrimitive?.long)
        assertEquals(29L, stream["ws_queue_accepted_total"]?.jsonPrimitive?.long)
        assertEquals(1L, stream["ws_queue_rejected_total"]?.jsonPrimitive?.long)
        dispatcher.stop()
    }

    @Test fun duplicateStartStreamDoesNotRestartActiveCapture() = runTest {
        mockIntentFlags()
        val streaming = mockk<StreamingManager>(relaxed = true)
        every { streaming.isActive() } returns true
        val dispatcher = dispatcher(backgroundScope, streaming)

        try {
            callback.captured!!(buildJsonObject { put("type", "start_stream") })
            runCurrent()

            verify(exactly = 0) { appContext.startActivity(any()) }
        } finally {
            dispatcher.stop()
            unmockkConstructor(Intent::class)
        }
    }

    @Test fun startStreamRequestsProjectionWhenCaptureIsNotActive() = runTest {
        mockIntentFlags()
        val streaming = mockk<StreamingManager>(relaxed = true)
        every { streaming.isActive() } returns false
        val dispatcher = dispatcher(backgroundScope, streaming)

        try {
            callback.captured!!(buildJsonObject { put("type", "start_stream") })
            runCurrent()

            verify(exactly = 1) { appContext.startActivity(any()) }
        } finally {
            dispatcher.stop()
            unmockkConstructor(Intent::class)
        }
    }

    private fun command() = buildJsonObject {
        put("type", "EXECUTE_DAG")
        put("command_id", "11111111-1111-4111-8111-111111111111")
        put("signed_at", System.currentTimeMillis() / 1000)
        put("payload", buildJsonObject { put("dag", buildJsonObject { put("fixture", true) }) })
    }

    private fun otaCommand() = buildJsonObject {
        put("type", "OTA_UPDATE")
        put("command_id", "44444444-4444-4444-8444-444444444444")
        put("signed_at", System.currentTimeMillis() / 1000)
        put("ttl_seconds", 180)
        put("payload", buildJsonObject {
            put("download_url", "https://management.test/update.apk")
            put("version", "1.2.16-dev")
            put("sha256", "a".repeat(64))
        })
    }

    @Test fun otaRetryAfterReconnectCannotDownloadOrInstallTwiceOnOneInstance() = runTest {
        val ota = mockk<OtaUpdateService>(relaxed = true)
        val finish = CompletableDeferred<Unit>()
        coEvery { ota.performUpdate(any()) } coAnswers { finish.await() }
        val first = dispatcher(backgroundScope, otaService = ota)
        val update = otaCommand()
        callback.captured!!(update)
        runCurrent()
        callback.captured!!(update)
        runCurrent()
        coVerify(exactly = 1) { ota.performUpdate(any()) }
        finish.complete(Unit)
        runCurrent()
        first.stop()

        val restarted = dispatcher(backgroundScope, otaService = ota)
        callback.captured!!(update)
        runCurrent()
        coVerify(exactly = 1) { ota.performUpdate(any()) }
        assertEquals("completed", messages.last()["status"]?.jsonPrimitive?.content)
        restarted.stop()
    }

    @Test fun interruptedOtaAfterProcessRestartReportsUnknownWithoutReinstall() = runTest {
        val ota = mockk<OtaUpdateService>(relaxed = true)
        val finish = CompletableDeferred<Unit>()
        coEvery { ota.performUpdate(any()) } coAnswers { finish.await() }
        val first = dispatcher(backgroundScope, otaService = ota)
        val update = otaCommand()
        callback.captured!!(update)
        runCurrent()
        coVerify(exactly = 1) { ota.performUpdate(any()) }
        first.stop()

        // A new process sees a durable started receipt but cannot know whether
        // the previous process installed the package before it disappeared.
        val restarted = dispatcher(backgroundScope, otaService = ota)
        callback.captured!!(update)
        runCurrent()
        coVerify(exactly = 1) { ota.performUpdate(any()) }
        assertEquals("failed", messages.last()["status"]?.jsonPrimitive?.content)
        assertEquals("execution_outcome_unknown_after_restart", messages.last()["error"]?.jsonPrimitive?.content)
        restarted.stop()
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

    @Test fun explicitDagPayloadTakesPrecedenceOverStaleCache() = runTest {
        val stale = buildJsonObject { put("account", "previous") }
        val fresh = buildJsonObject { put("account", "current") }
        every { cache.get("script", "same-legacy-hash") } returns ScriptCacheManager.CacheResult.Hit(stale, 0)
        val executed = slot<JsonObject>()
        coEvery { dag.execute(any(), capture(executed), any()) } returns buildJsonObject { put("success", true) }
        val dispatcher = dispatcher(backgroundScope)
        val msg = JsonObject(command() + ("payload" to buildJsonObject {
            put("dag", fresh); put("dag_name", "script"); put("dag_hash", "same-legacy-hash")
        }))
        callback.captured!!(msg)
        runCurrent()
        assertEquals(fresh, executed.captured)
        dispatcher.stop()
    }

    @Test fun uncertainDagOutcomeIsDurableAndDuplicateCannotRerunIt() = runTest {
        coEvery { dag.execute(any(), any(), any()) } throws RootCommandOutcomeUnknownException()
        val dispatcher = dispatcher(backgroundScope)
        repeat(2) { callback.captured!!(command()); runCurrent() }
        coVerify(exactly = 1) { dag.execute(any(), any(), any()) }
        val pending = journal().pending().single()
        assertEquals("failed", pending["status"]!!.jsonPrimitive.content)
        assertTrue(pending["error"]!!.jsonPrimitive.content.contains("unknown"))
        dispatcher.stop()
    }

    @Test fun uncertainLiveTapDoesNotEscapeIntoApplicationScope() = runTest {
        every { adb.tap(any(), any()) } throws RootCommandOutcomeUnknownException()
        val dispatcher = dispatcher(backgroundScope)
        callback.captured!!(buildJsonObject { put("type", "touch_tap"); put("x", 10); put("y", 20) })
        runCurrent()
        verify(exactly = 1) { adb.tap(10, 20) }
        dispatcher.stop()
        // runTest also rejects any uncaught child-coroutine failure.
    }

    @Test fun uncertainLiveSwipeDoesNotEscapeIntoApplicationScope() = runTest {
        every { adb.swipe(any(), any(), any(), any(), any()) } throws RootCommandOutcomeUnknownException()
        val dispatcher = dispatcher(backgroundScope)
        callback.captured!!(buildJsonObject {
            put("type", "touch_swipe"); put("x1", 1); put("y1", 2); put("x2", 3); put("y2", 4)
        })
        runCurrent()
        verify(exactly = 1) { adb.swipe(1, 2, 3, 4, 300) }
        dispatcher.stop()
    }

    @Test fun failedAcknowledgementWriteKeepsResultAndDoesNotCrashApplicationScope() = runTest {
        coEvery { dag.execute(any(), any(), any()) } returns buildJsonObject { put("success", true) }
        val dispatcher = dispatcher(backgroundScope)
        callback.captured!!(command())
        runCurrent()
        val ack = buildJsonObject {
            put("type", "result_ack"); put("command_id", command().getValue("command_id"))
        }
        receipts.writable = false
        callback.captured!!(ack)
        runCurrent()
        assertEquals(1, journal().pending().size)
        receipts.writable = true
        callback.captured!!(ack)
        runCurrent()
        assertTrue(journal().pending().isEmpty())
        dispatcher.stop()
        // runTest fails on an uncaught exception from the application's launch callback.
    }

    @Test fun backendNoopKeepaliveIsIgnoredWithoutCommandParseWarning() = runTest {
        val warnings = mutableListOf<String>()
        val tree = object : Timber.Tree() {
            override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
                if (priority >= android.util.Log.WARN) warnings += message
            }
        }
        Timber.plant(tree)
        try {
            val dispatcher = dispatcher(backgroundScope)
            callback.captured!!(buildJsonObject { put("type", "noop") })
            runCurrent()
            assertTrue(warnings.none { it.contains("Cannot parse command") })
            assertTrue(messages.isEmpty())
            coVerify(exactly = 0) { dag.execute(any(), any(), any()) }
            dispatcher.stop()
        } finally {
            Timber.uproot(tree)
        }
    }
}
