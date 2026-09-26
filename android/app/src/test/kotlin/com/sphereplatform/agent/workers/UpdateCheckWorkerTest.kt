package com.sphereplatform.agent.workers

import android.app.Application
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.ota.OtaUserActionRequiredException
import com.sphereplatform.agent.provisioning.InstanceRegistrationGuard
import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.IOException

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class UpdateCheckWorkerTest {
    private val auth = mockk<AuthTokenStore>(relaxed = true)
    private val registrationGuard = mockk<InstanceRegistrationGuard>(relaxed = true)
    private val ota = mockk<OtaUpdateService>(relaxed = true)
    private val requests = mutableListOf<Request>()
    private var code = 200
    private var body = """{"update_available":false}"""
    private var networkFailure: IOException? = null
    private val client = OkHttpClient.Builder().addInterceptor { chain ->
        requests.add(chain.request())
        networkFailure?.let { throw it }
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
            .code(code).message("fixture").body(body.toResponseBody()).build()
    }.build()

    @Before fun setup() {
        every { auth.getServerUrl() } returns "https://management.test"
        every { auth.getToken() } returns "copied-access-token"
        coEvery { auth.getFreshToken() } returns "fresh-device-token"
    }

    private fun worker() = UpdateCheckWorker(RuntimeEnvironment.getApplication(),
        mockk<WorkerParameters>(relaxed = true), auth, registrationGuard, ota, client)

    private fun release(versionCode: Int = BuildConfig.VERSION_CODE + 1) = """
        {"update_available":true,"version_code":$versionCode,"version_name":"next",
        "download_url":"https://management.test/update.apk","sha256":"${"a".repeat(64)}"}
    """.trimIndent()

    @Test fun `transient server failure requests backoff instead of next six hour period`() = runTest {
        code = 503
        assertEquals(Result.retry(), worker().doWork())
        coVerify(exactly = 0) { ota.performUpdate(any()) }
    }

    @Test fun `copied credentials are not used for OTA catalog before clone rebind succeeds`() = runTest {
        coEvery { registrationGuard.ensureRegistered() } throws IOException("clone rebind unavailable")

        assertEquals(Result.retry(), worker().doWork())

        coVerify(exactly = 1) { registrationGuard.ensureRegistered() }
        coVerify(exactly = 0) { auth.getFreshToken() }
        assertTrue("OTA catalog request must not use copied credentials", requests.isEmpty())
    }

    @Test fun `rate limiting requests backoff`() = runTest {
        code = 429
        assertEquals(Result.retry(), worker().doWork())
    }

    @Test fun `expired credential response retries fresh credential acquisition`() = runTest {
        code = 401
        assertEquals(Result.retry(), worker().doWork())
        code = 200
        assertEquals(Result.success(), worker().doWork())
        coVerify(exactly = 2) { auth.getFreshToken() }
    }

    @Test fun `token refresh exception participates in retry policy`() = runTest {
        coEvery { auth.getFreshToken() } throws IOException("refresh connection reset")
        assertEquals(Result.retry(), worker().doWork())
        assertTrue(requests.isEmpty())
    }

    @Test fun `refresh completing after route recovery uses current management address`() = runTest {
        coEvery { auth.getFreshToken() } coAnswers {
            every { auth.getServerUrl() } returns "https://recovered.test/"
            "fresh-device-token"
        }
        assertEquals(Result.success(), worker().doWork())
        assertEquals("recovered.test", requests.single().url.host)
        assertEquals("fresh-device-token", requests.single().header("X-API-Key"))
    }

    @Test fun `explicit no update is success without invoking installer`() = runTest {
        assertEquals(Result.success(), worker().doWork())
        coVerify(exactly = 0) { ota.performUpdate(any()) }
    }

    @Test fun `new release reaches actual OTA service boundary once`() = runTest {
        body = release()
        assertEquals(Result.success(), worker().doWork())
        coVerify(exactly = 1) { ota.performUpdate(match { it.version == "next" && it.sha256 == "a".repeat(64) }) }
        assertEquals(BuildConfig.VERSION_CODE.toString(), requests.single().url.queryParameter("version_code"))
    }

    @Test fun `stale catalog response cannot trigger a same version reinstall`() = runTest {
        body = release(BuildConfig.VERSION_CODE)
        assertEquals(Result.success(), worker().doWork())
        coVerify(exactly = 0) { ota.performUpdate(any()) }
    }

    @Test fun `stale lower version cannot trigger a downgrade`() = runTest {
        body = release(BuildConfig.VERSION_CODE - 1)
        assertEquals(Result.success(), worker().doWork())
        coVerify(exactly = 0) { ota.performUpdate(any()) }
    }

    @Test fun `malformed successful body is not mistaken for no update`() = runTest {
        body = """{"detail":"gateway not ready"}"""
        assertEquals(Result.retry(), worker().doWork())
    }

    @Test fun `network failure requests retry`() = runTest {
        networkFailure = IOException("connection reset")
        assertEquals(Result.retry(), worker().doWork())
    }

    @Test fun `oversized metadata never reaches installer`() = runTest {
        body = "x".repeat(65537)
        assertEquals(Result.retry(), worker().doWork())
        coVerify(exactly = 0) { ota.performUpdate(any()) }
    }

    @Test fun `failed install requests retry`() = runTest {
        body = release()
        coEvery { ota.performUpdate(any()) } throws IOException("download interrupted")
        assertEquals(Result.retry(), worker().doWork())
    }

    @Test fun `installer user action is surfaced without retrying into repeated approval prompts`() = runTest {
        body = release()
        coEvery { ota.performUpdate(any()) } throws OtaUserActionRequiredException(sessionId = 42)

        assertEquals(Result.success(), worker().doWork())

        coVerify(exactly = 1) { ota.performUpdate(any()) }
    }

    @Test fun `worker cancellation during install is propagated to WorkManager`() = runTest {
        body = release()
        val stopped = CancellationException("worker stopped")
        coEvery { ota.performUpdate(any()) } throws stopped
        try {
            worker().doWork()
            fail("Cancellation was swallowed")
        } catch (e: CancellationException) {
            // Coroutine stack-trace recovery may copy the exception across IO.
            assertEquals(stopped.message, e.message)
        }
    }
}
