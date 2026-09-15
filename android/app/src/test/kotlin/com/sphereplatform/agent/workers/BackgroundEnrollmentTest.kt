package com.sphereplatform.agent.workers

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.work.CoroutineWorker
import androidx.work.ListenableWorker
import com.sphereplatform.agent.provisioning.CloneDetector
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.root.RootAutoStart
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.Lazy
import io.mockk.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.nio.file.Files
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Real workers, config parser, registration HTTP and token store; no OS/service/socket effects. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class BackgroundEnrollmentTest {
    private val url = "https://primary.invalid"
    private val backup = "https://backup.invalid"
    private val id = "11111111-1111-4111-8111-111111111111"
    private val key = "sphr_isolated_enrollment"
    private val memory = ConcurrentHashMap<String, Any>()
    private val requests = CopyOnWriteArrayList<Request>()
    private val startedIds = CopyOnWriteArrayList<String>()
    private var enrolled = false
    private var status = 201
    private var beforeReply: () -> Unit = {}
    private lateinit var context: Context
    private lateinit var directory: File
    private lateinit var client: OkHttpClient
    private lateinit var store: AuthTokenStore
    private lateinit var registration: DeviceRegistrationClient
    private lateinit var provisioner: ZeroTouchProvisioner

    @Before
    fun setup() {
        directory = Files.createTempDirectory("sphere-background-enrollment").toFile()
        context = mockk(relaxed = true) {
            every { applicationContext } returns this
            every { getSystemService(Context.RESTRICTIONS_SERVICE) } returns null
            every { getExternalFilesDir(null) } returns directory
            every { filesDir } returns directory
        }
        val prefs = mockk<EncryptedSharedPreferences> {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { getLong(any(), any()) } answers { memory[firstArg()] as? Long ?: secondArg() }
            every { contains(any()) } answers { memory.containsKey(firstArg()) }
            every { edit() } answers {
                val pending = mutableMapOf<String, Any?>()
                fun write() = pending.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { putLong(any(), any()) } answers { pending[firstArg()] = secondArg<Long>(); this@editor }
                    every { remove(any()) } answers { pending[firstArg()] = null; this@editor }
                    every { apply() } answers { write() }
                    every { commit() } answers { write(); true }
                }
            }
        }
        client = OkHttpClient.Builder().addInterceptor { chain ->
            requests.add(chain.request())
            beforeReply()
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("isolated")
                .body("""{"device_id":"$id","name":"isolated","access_token":"issued-access",
                    "refresh_token":"issued-refresh","expires_in":900,"server_url":"$url","is_new":true}""".toResponseBody()).build()
        }.build()
        store = AuthTokenStore(prefs, Lazy { client })
        val detector = mockk<CloneDetector>(relaxed = true) {
            every { getFingerprint() } returns "isolated-stable-fingerprint"
            every { getDeviceType() } returns "android"
        }
        registration = DeviceRegistrationClient(client, store, detector, Json)
        provisioner = mockk(relaxed = true)
        mockkObject(ServiceWatchdog.Companion, SphereAgentService.Companion, RootAutoStart)
        every { ServiceWatchdog.isEnrolled(any()) } answers { enrolled }
        every { ServiceWatchdog.markEnrolled(any()) } answers { enrolled = true }
        every { ServiceWatchdog.schedule(any()) } just Runs
        every { SphereAgentService.start(any()) } answers { startedIds.add(store.getDeviceId() ?: "MISSING"); Unit }
        every { RootAutoStart.ensureRunning(any()) } just Runs
    }

    @After
    fun cleanup() {
        unmockkObject(ServiceWatchdog.Companion, SphereAgentService.Companion, RootAutoStart)
        client.dispatcher.executorService.shutdown()
        assertTrue(client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        client.connectionPool.evictAll()
        File(directory, "sphere-agent-config.json").takeIf { it.exists() }?.let { check(it.delete()) }
        check(directory.delete())
    }

    private fun worker(kind: String): CoroutineWorker = if (kind == "auto")
        AutoEnrollmentWorker(context, mockk(relaxed = true), provisioner, registration, store)
    else KeepAliveWorker(context, mockk(relaxed = true), provisioner, registration, store)

    private fun configured(auto: Boolean = true, device: String? = null, fallback: String? = backup) {
        coEvery { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            url, key, deviceId = device, autoRegisterEnabled = auto, fallbackServerUrl = fallback,
        )
    }

    private suspend fun assertRegistration(kind: String) {
        configured()
        assertEquals(ListenableWorker.Result.success(), worker(kind).doWork())
        assertEquals("Bootstrap key must be consumed by registration, not saved as a session", 1, requests.size)
        assertEquals("/api/v1/devices/register", requests.single().url.encodedPath)
        assertEquals(key, requests.single().header("X-API-Key"))
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
        assertEquals(backup, memory["fallback_server_url"])
        assertTrue(enrolled)
        assertEquals(listOf(id), startedIds)
        coVerify(exactly = 0) { provisioner.fetchServerConfig() }
    }

    @Test fun `auto worker registers supplied bootstrap key before marking enrolled`() = runBlocking { assertRegistration("auto") }
    @Test fun `periodic worker registers before service captures device identity`() = runBlocking { assertRegistration("keep") }

    private fun generatedConfig() {
        File(directory, "sphere-agent-config.json").writeText("""{"server_url":"$url",
            "fallback_server_url":"$backup","enrollment_api_key":"$key","device_id":null,
            "features":{"auto_register":true}}""")
        provisioner = ZeroTouchProvisioner(context, "") { client }
    }

    private suspend fun assertGenerated(kind: String) {
        generatedConfig()
        assertEquals(ListenableWorker.Result.success(), worker(kind).doWork())
        assertEquals(1, requests.size)
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
        assertEquals(listOf(id), startedIds)
    }

    @Test fun `generated local config bootstraps auto worker without discovery HTTP`() = runBlocking { assertGenerated("auto") }
    @Test fun `generated local config bootstraps periodic worker without discovery HTTP`() = runBlocking { assertGenerated("keep") }

    @Test fun `JSON null identity stays absent and registration policy is parsed`() = runBlocking {
        generatedConfig()
        val config = provisioner.discoverConfig()!!
        assertNull(config.deviceId)
        assertTrue(config.autoRegisterEnabled)
    }

    @Test fun `server rejection cannot become successful enrollment`() = runBlocking {
        configured()
        status = 503
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertFalse(enrolled)
        assertNull(store.getToken())
        assertTrue(startedIds.isEmpty())
    }

    @Test fun `missing discovery is retried by the one shot boot worker`() = runBlocking {
        coEvery { provisioner.discoverConfig() } returns null
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertFalse(enrolled)
    }

    @Test fun `explicit legacy device identity and static key remain supported`() = runBlocking {
        configured(auto = false, device = id)
        assertEquals(ListenableWorker.Result.success(), worker("auto").doWork())
        assertTrue(requests.isEmpty())
        assertEquals(id, store.getDeviceId())
        assertEquals(key, store.getToken())
        assertTrue(enrolled)
    }

    @Test fun `two workers share enrollment while the server reply is pending`() = runBlocking {
        configured()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val actual = registration
        registration = mockk {
            coEvery { register(any(), any(), any(), any(), any(), any()) } coAnswers {
                entered.complete(Unit)
                release.await()
                actual.register(url, key, fallbackServerUrl = backup)
            }
        }
        val first = async(start = CoroutineStart.UNDISPATCHED) { worker("auto").doWork() }
        withTimeout(3_000) { entered.await() }
        val second = async(start = CoroutineStart.UNDISPATCHED) { worker("keep").doWork() }
        try {
            coVerify(exactly = 1) { registration.register(any(), any(), any(), any(), any(), any()) }
        } finally {
            release.complete(Unit)
            withTimeout(5_000) { awaitAll(first, second) }
        }
        assertEquals(1, requests.size)
        assertEquals(id, store.getDeviceId())
    }

    @Test fun `already issued identity starts service without registering again`() = runBlocking {
        store.saveServerRoutes(url, backup)
        store.saveDeviceId(id)
        store.saveTokens("issued-access", "issued-refresh", 900)
        enrolled = true
        assertEquals(ListenableWorker.Result.success(), worker("auto").doWork())
        assertEquals(listOf(id), startedIds)
        coVerify(exactly = 0) { provisioner.discoverConfig() }
        assertTrue(requests.isEmpty())
    }

    @Test fun `service start rejection retries activation without another SQL enrollment`() = runBlocking {
        configured()
        every { SphereAgentService.start(any()) } throws IllegalStateException("isolated OS start rejection")
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertEquals(id, store.getDeviceId())
        every { SphereAgentService.start(any()) } answers { startedIds.add(store.getDeviceId() ?: "MISSING"); Unit }
        assertEquals(ListenableWorker.Result.success(), worker("auto").doWork())
        assertEquals(1, requests.size)
        assertEquals(listOf(id), startedIds)
    }

    @Test fun `null JSON key is not a usable enrollment credential`() = runBlocking {
        File(directory, "sphere-agent-config.json").writeText("""{"server_url":"$url","api_key":null,"enrollment_api_key":null}""")
        provisioner = ZeroTouchProvisioner(context, "") { client }
        val config = provisioner.discoverConfig()
        // Dev may continue to its baked-in defaults; never accept the null-valued file.
        assertFalse(config?.source?.startsWith("file:") == true)
        assertNotEquals("null", config?.apiKey)
        assertTrue(requests.isEmpty())
    }

    @Test fun `temporary rate limit retries without marking enrollment`() = runBlocking {
        configured()
        status = 429
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertFalse(enrolled)
        assertNull(store.getDeviceId())
        assertTrue(startedIds.isEmpty())
    }

    @Test fun `request timeout response retries without marking enrollment`() = runBlocking {
        configured()
        status = 408
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertFalse(enrolled)
        assertNull(store.getToken())
    }

    @Test fun `permanent registration denial does not fall back to static key`() = runBlocking {
        configured()
        status = 401
        assertEquals(ListenableWorker.Result.failure(), worker("auto").doWork())
        assertEquals(1, requests.size)
        assertFalse(enrolled)
        assertNull(store.getToken())
        assertTrue(startedIds.isEmpty())
    }

    @Test fun `periodic failure preserves future ticks and retries registration next time`() = runBlocking {
        configured()
        status = 503
        assertEquals(ListenableWorker.Result.success(), worker("keep").doWork())
        assertFalse(enrolled)
        assertTrue(startedIds.isEmpty())
        status = 201
        assertEquals(ListenableWorker.Result.success(), worker("keep").doWork())
        assertTrue(enrolled)
        assertEquals(listOf("primary.invalid", "backup.invalid", "primary.invalid"), requests.map { it.url.host })
        assertEquals(listOf(id), startedIds)
    }

    @Test fun `missing local marker reactivates issued identity without registration`() = runBlocking {
        store.saveServerRoutes(url, backup)
        store.saveDeviceId(id)
        store.saveTokens("issued-access", "issued-refresh", 900)
        assertFalse(enrolled)
        assertEquals(ListenableWorker.Result.success(), worker("auto").doWork())
        assertTrue(enrolled)
        coVerify(exactly = 0) { provisioner.discoverConfig() }
        assertTrue(requests.isEmpty())
    }

    @Test fun `legacy missing or malformed ID requires registration`() = runBlocking {
        configured(auto = false, device = "emu-legacy")
        assertEquals(ListenableWorker.Result.success(), worker("auto").doWork())
        assertEquals(1, requests.size)
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
    }

    @Test fun `missing bootstrap key keeps boot retry pending`() = runBlocking {
        coEvery { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(url, "", autoRegisterEnabled = true)
        coEvery { provisioner.fetchServerConfig() } returns null
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertFalse(enrolled)
        assertTrue(startedIds.isEmpty())
    }

    @Test fun `cancelled discovery propagates from both workers`() = runBlocking {
        for (kind in listOf("auto", "keep")) {
            coEvery { provisioner.discoverConfig() } throws CancellationException("isolated stop")
            try {
                worker(kind).doWork()
                fail("Worker cancellation must propagate")
            } catch (_: CancellationException) { }
            assertFalse(enrolled)
            assertTrue(startedIds.isEmpty())
        }
    }

    @Test fun `cancelled enrollment waiter does not interrupt the active owner`() = runBlocking {
        configured()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val actual = registration
        registration = mockk {
            coEvery { register(any(), any(), any(), any(), any(), any()) } coAnswers {
                entered.complete(Unit)
                release.await()
                actual.register(url, key, fallbackServerUrl = backup)
            }
        }
        val first = async(start = CoroutineStart.UNDISPATCHED) { worker("auto").doWork() }
        withTimeout(3_000) { entered.await() }
        val waiter = async(start = CoroutineStart.UNDISPATCHED) { worker("keep").doWork() }
        try {
            waiter.cancelAndJoin()
            assertTrue(first.isActive)
            coVerify(exactly = 1) { registration.register(any(), any(), any(), any(), any(), any()) }
        } finally {
            release.complete(Unit)
            withTimeout(5_000) { first.await() }
        }
        assertEquals(1, requests.size)
        assertEquals(listOf(id), startedIds)
    }

    @Test fun `periodic enrolled device restarts service without discovery`() = runBlocking {
        store.saveServerRoutes(url, backup)
        store.saveDeviceId(id)
        store.saveTokens("issued-access", "issued-refresh", 900)
        enrolled = true
        assertEquals(ListenableWorker.Result.success(), worker("keep").doWork())
        assertEquals(listOf(id), startedIds)
        coVerify(exactly = 0) { provisioner.discoverConfig() }
        assertTrue(requests.isEmpty())
    }

    @Test fun `workers never mix a selected route with a key from a later discovery response`() = runBlocking {
        coEvery { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            url, "", autoRegisterEnabled = true)
        coEvery { provisioner.fetchServerConfig() } returns ZeroTouchProvisioner.ServerConfig(
            "https://other-installation.invalid", "test", true, true, "unrelated-key", "/ws/android", 120)
        assertEquals(ListenableWorker.Result.retry(), worker("auto").doWork())
        assertEquals(ListenableWorker.Result.success(), worker("keep").doWork())
        assertTrue(requests.isEmpty())
        assertNull(store.getDeviceId())
        assertFalse(enrolled)
        coVerify(exactly = 0) { provisioner.fetchServerConfig() }
    }

    private suspend fun assertForegroundWorkerRace(foregroundFirst: Boolean) = coroutineScope {
        configured()
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        beforeReply = { entered.countDown(); check(release.await(5, TimeUnit.SECONDS)) }
        suspend fun foreground() = store.reuseEnrollmentOrEnroll {
            registration.register(url, key, fallbackServerUrl = backup)
        }
        val first = async { if (foregroundFirst) foreground() else worker("auto").doWork() }
        try {
            assertTrue(withContext(Dispatchers.IO) { entered.await(5, TimeUnit.SECONDS) })
            val second = async(start = CoroutineStart.UNDISPATCHED) {
                if (foregroundFirst) worker("auto").doWork() else foreground()
            }
            release.countDown()
            first.await()
            second.await()
            assertEquals("One issued identity across foreground and worker", 1, requests.size)
            assertEquals(id, store.getDeviceId())
            assertEquals("issued-refresh", memory["refresh_token"])
            assertEquals(listOf(id), startedIds)
        } finally { release.countDown() }
    }

    @Test fun `foreground waits for worker registration without rotating its tokens`() = runBlocking {
        assertForegroundWorkerRace(foregroundFirst = false)
    }

    @Test fun `worker reuses foreground registration without another HTTP request`() = runBlocking {
        assertForegroundWorkerRace(foregroundFirst = true)
    }

    @Test fun `foreground retry reuses an already issued identity`() = runBlocking {
        configured()
        worker("auto").doWork()
        assertTrue(store.reuseEnrollmentOrEnroll { error("Must not register twice") })
        assertEquals(1, requests.size)
    }

    @Test fun `token without device id does not skip initial registration`() = runBlocking {
        memory["access_token"] = "partial-old-state"
        assertFalse(store.reuseEnrollmentOrEnroll { registration.register(url, key) })
        assertEquals(1, requests.size)
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
    }

    @Test fun `cancelled registration owner releases enrollment for the next worker`() = runBlocking {
        configured()
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        beforeReply = {
            if (requests.size == 1) { entered.countDown(); check(release.await(20, TimeUnit.SECONDS)) }
        }
        val first = launch(Dispatchers.Default) { worker("auto").doWork() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            first.cancel()
            assertEquals(true, withTimeoutOrNull(1_000) { first.join(); true })
            assertFalse(enrolled)
            assertTrue(startedIds.isEmpty())
            assertEquals(ListenableWorker.Result.success(), withTimeout(3_000) { worker("keep").doWork() })
            assertEquals(listOf(id), startedIds)
            assertEquals(2, requests.size)
        } finally {
            release.countDown()
            first.cancelAndJoin()
            withTimeout(5_000) { while (client.dispatcher.runningCallsCount() != 0) delay(5) }
        }
        assertEquals("issued-access", store.getToken())
        assertEquals(listOf(id), startedIds)
    }

    @Test fun `registration HTTP deadline returns worker retry and allows the next attempt`() = runBlocking {
        configured(fallback = null)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        beforeReply = {
            if (requests.size == 1) { entered.countDown(); check(release.await(20, TimeUnit.SECONDS)) }
        }
        val first = async(Dispatchers.Default) { worker("auto").doWork() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            assertEquals(ListenableWorker.Result.retry(), withTimeoutOrNull(12_000) { first.await() })
            assertFalse(enrolled)
            assertNull(store.getToken())
            assertTrue(startedIds.isEmpty())
            assertEquals(ListenableWorker.Result.success(), withTimeout(3_000) { worker("auto").doWork() })
            assertEquals(listOf(id), startedIds)
            assertEquals(2, requests.size)
        } finally {
            release.countDown()
            first.cancelAndJoin()
            withTimeout(5_000) { while (client.dispatcher.runningCallsCount() != 0) delay(5) }
        }
        assertEquals("issued-access", store.getToken())
        assertEquals(listOf(id), startedIds)
    }
}
