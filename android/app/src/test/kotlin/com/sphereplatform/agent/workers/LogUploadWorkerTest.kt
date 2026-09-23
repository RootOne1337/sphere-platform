package com.sphereplatform.agent.workers

import android.app.Application
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
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
    private val client = OkHttpClient.Builder().addInterceptor { chain ->
        requests += chain.request()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
            .code(200).message("fixture").body("accepted".toResponseBody()).build()
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
