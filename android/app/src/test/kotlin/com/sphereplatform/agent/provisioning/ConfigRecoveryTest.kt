package com.sphereplatform.agent.provisioning

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.service.ConfigWatchdog
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.ws.SphereWebSocketClient
import dagger.Lazy
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.BufferedSource
import okio.Source
import okio.Timeout
import okio.buffer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/** Actual provisioner/store/watchdog and OkHttp calls; interceptors replace all network IO. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class ConfigRecoveryTest {
    private val memory = ConcurrentHashMap<String, Any>()
    private val calls = CopyOnWriteArrayList<Call>()
    private val requests = CopyOnWriteArrayList<Request>()
    private val entered = CountDownLatch(1)
    private val release = CountDownLatch(1)
    private val reconnects = AtomicInteger()
    private var holdBeforeReconnect = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var client: OkHttpClient
    private lateinit var store: AuthTokenStore
    private lateinit var provisioner: ZeroTouchProvisioner
    private lateinit var watchdog: ConfigWatchdog
    private var respond: (Interceptor.Chain) -> Response = { response(it.request()) }
    private val initialUrl = "https://primary.invalid"
    private val discoveredUrl = "https://discovered.invalid"
    private val payload = """{"server_url":"$discoveredUrl"}"""

    private fun response(request: Request, body: ResponseBody = payload.toResponseBody(), code: Int = 200) =
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(code).message("isolated").body(body).build()

    @Before
    fun setup() {
        memory.putAll(mapOf("access_token" to "issued-device-jwt", "server_url" to initialUrl))
        val prefs = mockk<EncryptedSharedPreferences> {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { edit() } answers {
                val pending = mutableMapOf<String, String?>()
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { apply() } answers { pending.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v } }
                    every { commit() } answers { pending.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }; true }
                }
            }
        }
        client = OkHttpClient.Builder().addInterceptor { chain ->
            calls.add(chain.call())
            requests.add(chain.request())
            respond(chain)
        }.build()
        store = AuthTokenStore(prefs, Lazy { client })
        provisioner = provisionerAt("https://config.invalid/api/v1/config/agent")
        val ws = mockk<SphereWebSocketClient>(relaxed = true) {
            every { isConnected } answers {
                if (holdBeforeReconnect) {
                    entered.countDown()
                    check(release.await(20, TimeUnit.SECONDS)) { "Test must release reconnect decision" }
                }
                false
            }
            every { forceReconnectNow() } answers { reconnects.incrementAndGet(); Unit }
        }
        watchdog = ConfigWatchdog(provisioner, store, ws, scope)
    }

    private fun provisionerAt(url: String) = ZeroTouchProvisioner(mockk(relaxed = true), url) { client }

    @After
    fun cleanup() = runBlocking {
        // Release transport/decision gates before stop takes the watchdog state lock.
        release.countDown()
        watchdog.stop()
        scope.cancel()
        withTimeout(5_000) { scope.coroutineContext[Job]!!.join() }
        client.dispatcher.executorService.shutdown()
        assertTrue("HTTP workers must finish", client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        client.connectionPool.evictAll()
    }

    private fun holdHeaders() {
        respond = {
            entered.countDown()
            check(release.await(20, TimeUnit.SECONDS)) { "Test must release headers" }
            response(it.request())
        }
    }

    private fun awaitEntered() = assertTrue(entered.await(5, TimeUnit.SECONDS))

    private suspend fun eventually(predicate: () -> Boolean) = withTimeout(3_000) {
        while (!predicate()) delay(10)
    }

    private suspend fun settleChecks() = withTimeout(3_000) {
        scope.coroutineContext[Job]!!.children.toList().joinAll()
        while (client.dispatcher.runningCallsCount() != 0) delay(10)
    }

    @Test
    fun `enrolled watchdog discovers public config without misusing device JWT as API key`() = runBlocking {
        holdBeforeReconnect = true
        respond = { response(it.request(), code = if (it.request().header("X-API-Key") == null) 200 else 401) }
        watchdog.forceCheck()
        eventually { requests.isNotEmpty() }
        assertNull("Discovery must not forward device JWT to the config host", requests.single().header("X-API-Key"))
        assertNull(requests.single().header("Authorization"))
        assertNull(requests.single().header("Cookie"))
        eventually { memory["primary_server_url"] == discoveredUrl }
        awaitEntered()
        // Preference commit is visible before the reconnect decision completes.
        assertEquals(0, reconnects.get())
        release.countDown()
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(1, reconnects.get())
        assertEquals("issued-device-jwt", store.getToken())
    }

    @Test
    fun `ten second discovery deadline cancels stuck HTTP and permits another request`() = runBlocking {
        holdHeaders()
        val lookup = async(Dispatchers.Default) { provisioner.fetchServerConfig() }
        try {
            awaitEntered()
            assertEquals("HTTP must finish while headers are still held", true,
                withTimeoutOrNull(12_000) { assertNull(lookup.await()); true })
            assertTrue(calls.first().isCanceled())
            respond = { response(it.request()) }
            assertEquals(discoveredUrl, withTimeout(2_000) { provisioner.fetchServerConfig() }?.serverUrl)
        } finally {
            release.countDown()
            lookup.cancelAndJoin()
        }
    }

    @Test
    fun `parent cancellation cancels discovery without waiting for held headers`() = runBlocking {
        holdHeaders()
        val lookup = async(Dispatchers.Default) { provisioner.fetchServerConfig() }
        try {
            awaitEntered()
            lookup.cancel()
            assertEquals(true, withTimeoutOrNull(1_000) { lookup.join(); true })
            assertTrue(calls.single().isCanceled())
        } finally {
            release.countDown()
            lookup.cancelAndJoin()
        }
    }

    @Test
    fun `oversized chunked config is rejected before reading the entire body`() = runBlocking {
        val bytes = Buffer().writeUtf8(payload + " ".repeat(256 * 1024))
        val read = AtomicLong()
        val closed = CountDownLatch(1)
        val source = object : Source {
            override fun read(sink: Buffer, byteCount: Long): Long = bytes.read(sink, byteCount).also { if (it > 0) read.addAndGet(it) }
            override fun timeout() = Timeout.NONE
            override fun close() { closed.countDown() }
        }.buffer()
        val body = object : ResponseBody() {
            override fun contentType() = null
            override fun contentLength() = -1L
            override fun source(): BufferedSource = source
        }
        respond = { response(it.request(), body) }
        assertNull("Truncating after string() accepts an oversized JSON prefix", provisioner.fetchServerConfig())
        assertTrue(read.get() <= 64 * 1024 + 8192)
        assertTrue(closed.await(1, TimeUnit.SECONDS))
    }

    @Test
    fun `sixty four forced checks share one pending HTTP request`() = runBlocking {
        holdHeaders()
        repeat(64) { watchdog.forceCheck() }
        awaitEntered()
        delay(250)
        assertEquals("Reconnect signals must not create parallel config calls", 1, requests.size)
        release.countDown()
        eventually { reconnects.get() == 1 }
    }

    @Test
    fun `stop cancels pending discovery and late response cannot change route`() = runBlocking {
        holdHeaders()
        watchdog.forceCheck()
        awaitEntered()
        watchdog.stop()
        eventually { calls.single().isCanceled() }
        release.countDown()
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `response from earlier route cannot overwrite a local route change`() = runBlocking {
        holdHeaders()
        watchdog.forceCheck()
        awaitEntered()
        store.saveServerUrl("https://operator-selected.invalid")
        release.countDown()
        settleChecks()
        assertEquals("https://operator-selected.invalid", store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `stopped watchdog ignores further circuit notifications`() = runBlocking {
        watchdog.stop()
        repeat(3) { watchdog.forceCheck() }
        settleChecks()
        assertTrue(requests.isEmpty())
        assertEquals(initialUrl, store.getServerUrl())
    }

    @Test
    fun `invalid discovered URL cannot replace a usable route`() = runBlocking {
        respond = { response(it.request(), """{"server_url":"not-a-server"}""".toResponseBody()) }
        watchdog.forceCheck()
        eventually { requests.isNotEmpty() }
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `same route does not reconnect or change credentials`() = runBlocking {
        respond = { response(it.request(), """{"server_url":"$initialUrl/"}""".toResponseBody()) }
        watchdog.forceCheck()
        eventually { requests.isNotEmpty() }
        settleChecks()
        assertEquals(0, reconnects.get())
        assertEquals("issued-device-jwt", store.getToken())
    }

    @Test
    fun `server unavailable preserves current route`() = runBlocking {
        respond = { response(it.request(), code = 503) }
        watchdog.forceCheck()
        eventually { requests.isNotEmpty() }
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `malformed response preserves current route`() = runBlocking {
        respond = { response(it.request(), "broken-json".toResponseBody()) }
        watchdog.forceCheck()
        eventually { requests.isNotEmpty() }
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `blank config endpoint performs no network request`() = runBlocking {
        assertNull(provisionerAt("").fetchServerConfig())
        assertTrue(requests.isEmpty())
    }

    @Test
    fun `local route change and restore still invalidates older response`() = runBlocking {
        holdHeaders()
        watchdog.forceCheck()
        awaitEntered()
        store.saveServerUrl("https://operator-selected.invalid")
        store.saveServerUrl(initialUrl)
        release.countDown()
        settleChecks()
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `cancelling periodic owner also cancels its forced request`() = runBlocking {
        holdHeaders()
        val owner = launch(start = CoroutineStart.UNDISPATCHED) { watchdog.run() }
        try {
            watchdog.forceCheck()
            awaitEntered()
            withTimeout(1_000) { owner.cancelAndJoin() }
            assertTrue(calls.single().isCanceled())
            release.countDown()
            settleChecks()
            assertEquals(initialUrl, store.getServerUrl())
            assertEquals(0, reconnects.get())
        } finally { owner.cancelAndJoin() }
    }

    @Test
    fun `second periodic owner cannot cancel the active owner or duplicate its request`() = runBlocking {
        holdHeaders()
        val first = launch(start = CoroutineStart.UNDISPATCHED) { watchdog.run() }
        try {
            watchdog.forceCheck()
            awaitEntered()
            val second = launch(start = CoroutineStart.UNDISPATCHED) { watchdog.run() }
            withTimeout(1_000) { second.join() }
            assertTrue(first.isActive)
            assertFalse(calls.single().isCanceled())
            assertEquals(1, requests.size)
        } finally { first.cancelAndJoin() }
    }

    @Test
    fun `restart accepts fresh response and ignores prior generation response`() = runBlocking {
        holdHeaders()
        watchdog.forceCheck()
        awaitEntered()
        watchdog.stop()
        respond = { response(it.request(), """{"server_url":"https://new-generation.invalid"}""".toResponseBody()) }
        val owner = launch(start = CoroutineStart.UNDISPATCHED) { watchdog.run() }
        try {
            watchdog.forceCheck()
            eventually { reconnects.get() == 1 }
            release.countDown()
            settleChecks()
            assertTrue(calls.first().isCanceled())
            assertEquals("https://new-generation.invalid", memory["primary_server_url"])
            assertEquals(initialUrl, store.getServerUrl())
            assertEquals(1, reconnects.get())
        } finally { owner.cancelAndJoin() }
    }

    @Test
    fun `cancelled body read closes late response without applying it`() = runBlocking {
        val closed = CountDownLatch(1)
        val bytes = Buffer().writeUtf8(payload)
        val source = object : Source {
            override fun read(sink: Buffer, byteCount: Long): Long {
                entered.countDown()
                check(release.await(10, TimeUnit.SECONDS))
                return bytes.read(sink, byteCount)
            }
            override fun timeout() = Timeout.NONE
            override fun close() { closed.countDown() }
        }.buffer()
        val body = object : ResponseBody() {
            override fun contentType() = null
            override fun contentLength() = -1L
            override fun source(): BufferedSource = source
        }
        respond = { response(it.request(), body) }
        watchdog.forceCheck()
        awaitEntered()
        watchdog.stop()
        eventually { calls.single().isCanceled() }
        release.countDown()
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertEquals(initialUrl, store.getServerUrl())
        assertEquals(0, reconnects.get())
    }

    @Test
    fun `discovery rejects credential and query bearing server URLs`() = runBlocking {
        for (url in listOf("https://name:secret@server.invalid", "$initialUrl?route=x", "$initialUrl#fragment")) {
            respond = { response(it.request(), """{"server_url":"$url"}""".toResponseBody()) }
            assertNull(provisioner.fetchServerConfig())
        }
        assertEquals(initialUrl, store.getServerUrl())
    }

    @Test
    fun `public config still parses bootstrap fields without sending credentials`() = runBlocking {
        respond = { response(it.request(), """{
            "server_url":"$discoveredUrl", "environment":"isolated",
            "features":{"auto_register":true}, "enrollment_api_key":"test-bootstrap-key",
            "ws_path":"/ws/android", "config_poll_interval_seconds":60
        }""".toResponseBody()) }
        val config = provisioner.fetchServerConfig()!!
        assertEquals(discoveredUrl, config.serverUrl)
        assertEquals("isolated", config.environment)
        assertTrue(config.autoRegister)
        assertEquals("test-bootstrap-key", config.enrollmentApiKey)
        assertEquals(60, config.configPollIntervalSeconds)
        assertNull(requests.single().header("X-API-Key"))
    }

    @Test
    fun `blank endpoint periodic run returns normally without network`() = runBlocking {
        val disabled = ConfigWatchdog(provisionerAt(""), store, mockk(relaxed = true), scope)
        withTimeout(1_000) { disabled.run() }
        disabled.forceCheck()
        delay(100)
        assertTrue(requests.isEmpty())
    }
}
