package com.sphereplatform.agent.ota

import android.app.Application
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.provisioning.InstanceRegistrationGuard
import io.mockk.every
import io.mockk.coEvery
import io.mockk.mockk
import io.mockk.spyk
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import okio.Source
import okio.Timeout
import okio.buffer
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Real service/download/hash/files; only the Android installer boundary is stubbed. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class OtaUpdateServiceRecoveryTest {
    private val auth = mockk<AuthTokenStore>(relaxed = true)
    private val registrationGuard = mockk<InstanceRegistrationGuard>(relaxed = true)
    private val bytes = ByteArray(32768) { (it % 127).toByte() }
    private val installs = AtomicInteger()
    private val dir get() = File(RuntimeEnvironment.getApplication().filesDir, "ota")

    @Before fun setup() {
        every { auth.getServerUrl() } returns "https://management.test"
        every { auth.connectionRoutesSnapshot() } returns
            AuthTokenStore.ConnectionRoutes(1L, listOf("https://management.test"))
        every { auth.getToken() } returns "fixture-token"
        coEvery { registrationGuard.ensureRegistered() } returns Unit
        // Robolectric application data is isolated for each test.
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    private fun payload(version: String = "next", hash: String = sha256(bytes)) =
        OtaUpdatePayload(
            "https://management.test/update.apk", version, hash,
            version_code = BuildConfig.VERSION_CODE + 1,
        )

    private fun service(client: OkHttpClient, install: (File) -> Unit = {
        assertArrayEquals(bytes, it.readBytes())
        installs.incrementAndGet()
    }): OtaUpdateService {
        val ota = spyk(
            OtaUpdateService(
                RuntimeEnvironment.getApplication(), client, auth, registrationGuard,
                mockk<PackageInstallerResultAwaiter>(),
            ),
            recordPrivateCalls = true,
        )
        coEvery { ota["install"](any<File>(), any<Int>()) } coAnswers { install(firstArg()) }
        return ota
    }

    private fun client(body: () -> ResponseBody, code: Int = 200) = OkHttpClient.Builder()
        .addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(code).message("fixture").body(body()).build()
        }.build()

    private fun brokenBody() = object : ResponseBody() {
        override fun contentType() = null
        override fun contentLength() = -1L
        override fun source() = object : Source {
            private var reads = 0
            override fun read(sink: Buffer, byteCount: Long): Long {
                if (reads++ > 0) throw IOException("fixture connection reset after partial body")
                sink.write(bytes, 0, 8192)
                return 8192
            }
            override fun timeout() = Timeout.NONE
            override fun close() = Unit
        }.buffer()
    }

    @Test fun `OTA accepts signed primary artifact while management uses fallback`() = runBlocking {
        every { auth.getServerUrl() } returns "https://fallback.test"
        every { auth.connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(
            2L, listOf("https://fallback.test", "https://management.test"),
        )

        service(client({ bytes.toResponseBody() })).performUpdate(payload())

        assertEquals(1, installs.get())
    }

    @Test fun `OTA rejects an artifact on an untrusted origin before network access`() = runBlocking {
        every { auth.connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(
            2L, listOf("https://management.test", "https://fallback.test"),
        )
        val requests = AtomicInteger()
        val ota = service(client({ requests.incrementAndGet(); bytes.toResponseBody() }))
        for (url in listOf(
            "https://management.test:8443/update.apk",
            "https://third-party.test/update.apk",
            "http://management.test/update.apk",
            "https://user:password@management.test/update.apk",
        )) {
            try {
                ota.performUpdate(payload().copy(download_url = url))
                fail("Untrusted OTA URL was accepted: $url")
            } catch (expected: IllegalArgumentException) {
                assertEquals(0, requests.get())
                assertEquals(0, installs.get())
            }
        }
    }

    @Test fun `interrupted body removes partial file and a subsequent attempt can install`() = runBlocking {
        var broken = true
        val ota = service(client({ if (broken) brokenBody() else bytes.toResponseBody() }))
        try {
            ota.performUpdate(payload())
            fail("Broken body was accepted")
        } catch (expected: IOException) {
            assertTrue(expected.message!!.contains("connection reset"))
        }
        assertTrue("Partial APK survives a failed download", dir.listFiles().isNullOrEmpty())
        assertEquals(0, installs.get())
        broken = false
        ota.performUpdate(payload())
        assertEquals(1, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `one transient body reset is retried before waiting for the next work manager run`() = runBlocking {
        val attempts = AtomicInteger()
        val ota = service(client({
            if (attempts.getAndIncrement() == 0) brokenBody() else bytes.toResponseBody()
        }))

        ota.performUpdate(payload())

        assertEquals("the first interrupted transfer must trigger one bounded retry", 2, attempts.get())
        assertEquals(1, installs.get())
        assertTrue("Successful OTA leaves no staging file", dir.listFiles().isNullOrEmpty())
    }

    @Test fun `OTA download is blocked until copied clone credentials are rebound`() = runBlocking {
        val networkCalls = AtomicInteger()
        coEvery { registrationGuard.ensureRegistered() } throws IOException("clone rebind unavailable")
        val ota = service(client({
            networkCalls.incrementAndGet()
            bytes.toResponseBody()
        }))

        val failure = runCatching { ota.performUpdate(payload()) }.exceptionOrNull()

        assertTrue(failure is IOException)
        assertEquals("No download may use the copied bearer token", 0, networkCalls.get())
        assertEquals(0, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `repeated body resets stop after one fallback and remove both partial attempts`() = runBlocking {
        val attempts = AtomicInteger()
        val ota = service(client({
            attempts.incrementAndGet()
            brokenBody()
        }))

        try {
            ota.performUpdate(payload())
            fail("Repeated body resets must not be accepted")
        } catch (expected: IOException) {
            assertTrue(expected.message!!.contains("connection reset"))
        }

        assertEquals("each OTA execution gets at most one fallback", 2, attempts.get())
        assertEquals(0, installs.get())
        assertTrue("Failed OTA removes all partial staging data", dir.listFiles().isNullOrEmpty())
    }

    @Test fun `overlapping requests cannot overwrite or remove an APK being installed`() = runBlocking {
        val firstEntered = CountDownLatch(1)
        val releaseFirst = CountDownLatch(1)
        val secondEntered = CountDownLatch(1)
        val sequence = AtomicInteger()
        val ota = service(client({ bytes.toResponseBody() })) { file ->
            if (sequence.incrementAndGet() == 1) {
                firstEntered.countDown()
                assertTrue(releaseFirst.await(10, TimeUnit.SECONDS))
                assertArrayEquals("An overlapping update removed/replaced the install input", bytes, file.readBytes())
            } else {
                secondEntered.countDown()
            }
        }
        supervisorScope {
            val first = async(Dispatchers.IO) { ota.performUpdate(payload()) }
            var second: Deferred<Unit>? = null
            try {
                assertTrue(firstEntered.await(10, TimeUnit.SECONDS))
                second = async(Dispatchers.IO) { ota.performUpdate(payload()) }
                assertFalse("A second install entered while the first still owns its APK", secondEntered.await(750, TimeUnit.MILLISECONDS))
            } finally {
                releaseFirst.countDown()
                first.await()
                second?.await()
            }
        }
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `OTA operation does not complete before the installer reports its outcome`() = runBlocking {
        val installStarted = CompletableDeferred<File>()
        val releaseInstaller = CompletableDeferred<Unit>()
        val ota = spyk(
            OtaUpdateService(
                RuntimeEnvironment.getApplication(), client({ bytes.toResponseBody() }), auth,
                registrationGuard, mockk<PackageInstallerResultAwaiter>(),
            ),
            recordPrivateCalls = true,
        )
        coEvery { ota["install"](any<File>(), any<Int>()) } coAnswers {
            installStarted.complete(firstArg())
            releaseInstaller.await()
        }

        val update = async(Dispatchers.IO) { ota.performUpdate(payload()) }
        try {
            val stagedApk = withTimeout(2_000) { installStarted.await() }
            assertArrayEquals(bytes, stagedApk.readBytes())
            assertFalse("OTA must not report completion while Android installation is pending", update.isCompleted)
            releaseInstaller.complete(Unit)
            withTimeout(2_000) { update.await() }
            assertTrue(update.isCompleted)
        } finally {
            releaseInstaller.complete(Unit)
            update.cancelAndJoin()
        }
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `cancellation closes a real in flight HTTP download and removes its file`() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody(Buffer().write(bytes)).throttleBody(1024, 2, TimeUnit.SECONDS))
        server.start()
        // Route only this fixture's validated HTTPS URL to the loopback test socket.
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            chain.proceed(chain.request().newBuilder().url(server.url("/update.apk")).build())
        }.build()
        val ota = service(client)
        supervisorScope {
            val job = async(Dispatchers.IO) { ota.performUpdate(payload()) }
            try {
                withTimeout(5000) {
                    while (dir.listFiles()?.none { it.length() > 0 } != false) delay(10)
                }
                job.cancel()
                withTimeout(1500) { job.join() }
                assertTrue("Cancelled download left a file", dir.listFiles().isNullOrEmpty())
                assertEquals(0, installs.get())
            } finally {
                server.shutdown()
                job.cancelAndJoin()
            }
        }
    }

    @Test fun `service startup removes APKs left by process replacement but preserves other files`() {
        assertTrue(dir.mkdirs())
        val old = File(dir, "update_1.2.3-dev.apk").apply { writeBytes(bytes) }
        val interrupted = File(dir, "update_12345.apk").apply { writeBytes(bytes.take(100).toByteArray()) }
        val unrelated = File(dir, "diagnostic.txt").apply { writeText("keep") }
        service(client({ bytes.toResponseBody() }))
        assertFalse("Successful self-replacement left the old APK", old.exists())
        assertFalse(interrupted.exists())
        assertEquals("keep", unrelated.readText())
    }

    @Test fun `installer exception cleans up and permits a later attempt`() = runBlocking {
        var failInstall = true
        val ota = service(client({ bytes.toResponseBody() })) {
            if (failInstall) throw IOException("fixture installer failure")
            installs.incrementAndGet()
        }
        try {
            ota.performUpdate(payload())
            fail("Installer failure was swallowed")
        } catch (expected: IOException) {
            assertTrue(expected.message!!.contains("installer"))
        }
        assertTrue(dir.listFiles().isNullOrEmpty())
        failInstall = false
        ota.performUpdate(payload())
        assertEquals(1, installs.get())
    }

    @Test fun `version label cannot select the staging path`() = runBlocking {
        service(client({ bytes.toResponseBody() })).performUpdate(payload(version = "../../../not-a-filename"))
        assertEquals(1, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `oversized advertised APK is rejected before installation and cleaned up`() = runBlocking {
        val body = object : ResponseBody() {
            override fun contentType() = null
            override fun contentLength() = 200L * 1024 * 1024 + 1
            override fun source() = Buffer().write(bytes)
        }
        try {
            service(client({ body })).performUpdate(payload())
            fail("Oversized APK was accepted")
        } catch (expected: IllegalStateException) {
            assertTrue(expected.message!!.contains("200MB"))
        }
        assertEquals(0, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `checksum mismatch removes the file without invoking installer`() = runBlocking {
        val ota = service(client({ bytes.toResponseBody() }))
        try {
            ota.performUpdate(payload(hash = "0".repeat(64)))
            fail("Checksum mismatch was accepted")
        } catch (expected: IllegalStateException) {
            assertTrue(expected.message!!.contains("SHA-256 mismatch"))
        }
        assertEquals(0, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test fun `HTTP failure leaves no artifact and does not install`() = runBlocking {
        val ota = service(client({ bytes.toResponseBody() }, code = 503))
        try {
            ota.performUpdate(payload())
            fail("HTTP error was accepted")
        } catch (expected: IllegalStateException) {
            assertTrue(expected.message!!.contains("503"))
        }
        assertEquals(0, installs.get())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    private fun sha256(value: ByteArray) = MessageDigest.getInstance("SHA-256")
        .digest(value).joinToString("") { "%02x".format(it) }
}
