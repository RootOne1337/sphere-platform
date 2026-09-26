package com.sphereplatform.agent.workers

import android.app.Application
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
import com.sphereplatform.agent.logging.CrashHandler
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.logging.LogcatCollector
import com.sphereplatform.agent.provisioning.InstanceRegistrationGuard
import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.coVerifyOrder
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.IOException

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class LogUploadWorkerTest {
    private val auth = mockk<AuthTokenStore>(relaxed = true)
    private val registrationGuard = mockk<InstanceRegistrationGuard>(relaxed = true)
    private val loggingTree = mockk<FileLoggingTree>(relaxed = true)
    private val logcatCollector = mockk<LogcatCollector>(relaxed = true)
    private val requests = mutableListOf<Request>()
    private var responseCode = 200
    private var beforeResponse: (() -> Unit)? = null
    private val client = OkHttpClient.Builder().addInterceptor { chain ->
        requests += chain.request()
        beforeResponse?.invoke()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
            .code(responseCode).message("fixture").body("accepted".toResponseBody()).build()
    }.build()

    private fun worker() = LogUploadWorker(
        RuntimeEnvironment.getApplication(), mockk<WorkerParameters>(relaxed = true),
        auth, registrationGuard, loggingTree, logcatCollector, client,
    )

    @Test fun `copied credentials are not used for log upload before clone rebind succeeds`() = runTest {
        every { auth.getToken() } returns "copied-access-token"
        coEvery { registrationGuard.ensureRegistered() } throws IOException("clone rebind unavailable")

        assertEquals(Result.retry(), worker().doWork())

        coVerify(exactly = 1) { registrationGuard.ensureRegistered() }
        coVerify(exactly = 0) { auth.getFreshToken() }
        assertTrue("Log upload must not use the copied device identity", requests.isEmpty())
    }

    @Test fun `log upload occurs only after clone credentials have been rebound`() = runTest {
        every { auth.getToken() } returns "copied-access-token"
        every { auth.getServerUrl() } returns "https://management.test"
        every { auth.getDeviceId() } returns "device-after-rebind"
        coEvery { auth.getFreshToken() } returns "fresh-device-token"
        every { loggingTree.readRecentLogs(any()) } returns "sphere-file-logs"
        every { logcatCollector.collectSphereOnly(lines = 300) } returns "sphere-logcat"

        assertEquals(Result.success(), worker().doWork())

        coVerifyOrder {
            registrationGuard.ensureRegistered()
            auth.getFreshToken()
        }
        val request = requests.single()
        assertEquals("https", request.url.scheme)
        assertEquals("fresh-device-token", request.header("X-API-Key"))
        assertEquals("device-after-rebind", request.header("X-Device-Id"))
    }

    @Test fun `persisted crash record is uploaded and removed only after server accepts it`() = runTest {
        prepareUploadCredentials()
        val crashFile = CrashHandler.crashLogFile(RuntimeEnvironment.getApplication())
        crashFile.writeText("=== CRASH fixture ===\\njava.lang.IllegalStateException: stream failed")

        try {
            assertEquals(Result.success(), worker().doWork())

            val body = Buffer().also { requests.single().body!!.writeTo(it) }.readUtf8()
            assertTrue("crash evidence must reach remote diagnostics", body.contains("stream failed"))
            assertTrue("accepted crash evidence must not be uploaded on every retry", !crashFile.exists())
        } finally {
            crashFile.delete()
        }
    }

    @Test fun `crash record is retained when server rejects log upload`() = runTest {
        prepareUploadCredentials()
        responseCode = 503
        val crashFile = CrashHandler.crashLogFile(RuntimeEnvironment.getApplication())
        crashFile.writeText("=== CRASH fixture ===\\nretry me")

        try {
            assertEquals(Result.retry(), worker().doWork())

            assertTrue("failed upload must retain the only crash evidence", crashFile.exists())
            assertTrue(crashFile.readText().contains("retry me"))
        } finally {
            crashFile.delete()
        }
    }

    @Test fun `new crash arriving during upload is retained for the next attempt`() = runTest {
        prepareUploadCredentials()
        val crashFile = CrashHandler.crashLogFile(RuntimeEnvironment.getApplication())
        crashFile.writeText("=== CRASH first ===\\noriginal")
        beforeResponse = { crashFile.appendText("\\n=== CRASH later ===\\nnew evidence") }

        try {
            assertEquals(Result.success(), worker().doWork())

            assertTrue("a newer crash must not be deleted with the uploaded snapshot", crashFile.exists())
            assertTrue(crashFile.readText().contains("new evidence"))
        } finally {
            beforeResponse = null
            crashFile.delete()
        }
    }

    @Test fun `large logcat cannot exceed server entry cap or hide crash tail`() = runTest {
        prepareUploadCredentials()
        every { logcatCollector.collectSphereOnly(lines = 300) } returns "x".repeat(600 * 1024)
        every { loggingTree.readRecentWebSocketLifecycleLogs(any()) } returns
            "2026-09-26T16:28:08.033 I/SphereWebSocketClient: ws_lifecycle event=onFailure route_slot=0 phase=authenticated error_type=SocketTimeoutException\n"
        val crashFile = CrashHandler.crashLogFile(RuntimeEnvironment.getApplication())
        crashFile.writeText(
            "OLD_CRASH_MARKER" + "y".repeat(140 * 1024) + "NEW_CRASH_TAIL_MARKER",
        )

        try {
            assertEquals(Result.success(), worker().doWork())

            val body = Buffer().also { requests.single().body!!.writeTo(it) }.readByteArray()
            assertTrue("request must leave headroom under the backend 512 KiB limit", body.size <= 480 * 1024)
            val text = body.toString(Charsets.UTF_8)
            assertTrue("newest crash evidence must survive whole-request truncation", text.contains("NEW_CRASH_TAIL_MARKER"))
            assertTrue("priority WebSocket evidence must survive a saturated logcat upload", text.contains("ws_lifecycle event=onFailure"))
            assertTrue("oldest crash bytes are intentionally outside the bounded tail", !text.contains("OLD_CRASH_MARKER"))
        } finally {
            crashFile.delete()
        }
    }

    @Test fun `priority websocket events are not duplicated when present in the regular tail`() = runTest {
        prepareUploadCredentials()
        val event = "2026-09-26T17:08:19.567 I/SphereWebSocketClient: ws_lifecycle event=onFailure attempt_id=1 route_slot=0 phase=authenticated error_type=SocketTimeoutException"
        every { loggingTree.readRecentLogs(any()) } returns "ordinary log line\n$event\n"
        every { loggingTree.readRecentWebSocketLifecycleLogs(any()) } returns "$event\n"

        assertEquals(Result.success(), worker().doWork())

        val body = Buffer().also { requests.single().body!!.writeTo(it) }.readUtf8()
        assertEquals(
            "upload must contain a lifecycle event once even when both bounded sources return it",
            1,
            body.lineSequence().count { it.contains("ws_lifecycle event=onFailure") },
        )
    }

    private fun prepareUploadCredentials() {
        every { auth.getToken() } returns "access-token"
        every { auth.getServerUrl() } returns "https://management.test"
        every { auth.getDeviceId() } returns "device-1"
        coEvery { auth.getFreshToken() } returns "fresh-device-token"
        every { loggingTree.readRecentLogs(any()) } returns "sphere-file-logs"
        every { logcatCollector.collectSphereOnly(lines = 300) } returns "sphere-logcat"
    }

    @Test fun `worker cancellation during clone rebind propagates`() = runTest {
        every { auth.getToken() } returns "copied-access-token"
        val stopped = CancellationException("worker stopped")
        coEvery { registrationGuard.ensureRegistered() } throws stopped

        try {
            worker().doWork()
            throw AssertionError("Cancellation must reach WorkManager")
        } catch (actual: CancellationException) {
            assertEquals(stopped.message, actual.message)
        }
    }
}
