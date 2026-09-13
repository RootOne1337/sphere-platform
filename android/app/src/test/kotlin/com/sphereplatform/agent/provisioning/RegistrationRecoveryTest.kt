package com.sphereplatform.agent.provisioning

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.Lazy
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicBoolean

/** Actual registration, token store and OkHttp; synthetic network, preferences and device metadata. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class RegistrationRecoveryTest {
    private val url = "https://primary.invalid"
    private val backup = "https://backup.invalid"
    private val id = "11111111-1111-4111-8111-111111111111"
    private val memory = ConcurrentHashMap<String, Any>()
    private val calls = CopyOnWriteArrayList<Call>()
    private val entered = CountDownLatch(1)
    private val release = CountDownLatch(1)
    private val closed = CountDownLatch(1)
    private lateinit var client: OkHttpClient
    private lateinit var store: AuthTokenStore
    private lateinit var registration: DeviceRegistrationClient
    private var respond: (Interceptor.Chain) -> Response = { response(it.request()) }
    private val payload get() = """{"device_id":"$id","name":"isolated","access_token":"issued-access",
        "refresh_token":"issued-refresh","expires_in":900,"server_url":"$url","is_new":true}"""

    private fun response(request: Request, body: ResponseBody = payload.toResponseBody(), code: Int = 201) =
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(code).message("isolated").body(body).build()

    @Before fun setup() {
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
        client = OkHttpClient.Builder().callTimeout(0, TimeUnit.MILLISECONDS).addInterceptor { chain ->
            calls.add(chain.call())
            respond(chain)
        }.build()
        store = AuthTokenStore(prefs, Lazy { client })
        val detector = mockk<CloneDetector>(relaxed = true) {
            every { getFingerprint() } returns "isolated-stable-fingerprint"
            every { getDeviceType() } returns "android"
        }
        registration = DeviceRegistrationClient(client, store, detector, Json)
    }

    @After fun cleanup() {
        release.countDown()
        client.dispatcher.executorService.shutdown()
        assertTrue(client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        client.connectionPool.evictAll()
    }

    private suspend fun register(withFallback: Boolean = false) =
        registration.register(url, "sphr_isolated", fallbackServerUrl = backup.takeIf { withFallback })
    private fun awaitEntered() = assertTrue("Registration must reach held transport", entered.await(5, TimeUnit.SECONDS))
    private suspend fun awaitIdle() = withTimeout(5_000) {
        while (client.dispatcher.runningCallsCount() != 0 || client.dispatcher.queuedCallsCount() != 0) delay(5)
    }

    private fun holdHeaders() {
        respond = {
            entered.countDown()
            check(release.await(20, TimeUnit.SECONDS))
            response(it.request())
        }
    }

    private fun trackedBody(content: String = payload, hold: Boolean = false, read: AtomicLong = AtomicLong()): ResponseBody {
        val bytes = Buffer().writeUtf8(content)
        val source = object : Source {
            override fun read(sink: Buffer, byteCount: Long): Long {
                if (hold) { entered.countDown(); check(release.await(20, TimeUnit.SECONDS)) }
                val count = bytes.read(sink, byteCount)
                if (count > 0) read.addAndGet(count)
                return count
            }
            override fun timeout() = Timeout.NONE
            override fun close() { closed.countDown() }
        }.buffer()
        return object : ResponseBody() {
            override fun contentType() = "application/json".toMediaType()
            override fun contentLength() = -1L
            override fun source(): BufferedSource = source
        }
    }

    @Test fun `registration has its own ten second deadline without changing shared WS timeouts`() = runBlocking {
        holdHeaders()
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            awaitEntered()
            val completed = withTimeoutOrNull(12_000) { pending.await() }
            assertTrue("A stalled request must fail at its own HTTP deadline", completed is IOException)
            assertTrue(calls.single().isCanceled())
            assertEquals(0, client.callTimeoutMillis)
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `stopping registration cancels actual HTTP without waiting for headers`() = runBlocking {
        holdHeaders()
        val pending = launch(Dispatchers.Default) { register(withFallback = true) }
        try {
            awaitEntered()
            pending.cancel()
            assertEquals(true, withTimeoutOrNull(1_000) { pending.join(); true })
            assertTrue(calls.single().isCanceled())
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `cancelled body read cannot persist a late registration reply`() = runBlocking {
        respond = { response(it.request(), trackedBody(hold = true)) }
        val pending = launch(Dispatchers.Default) { register() }
        try {
            awaitEntered()
            pending.cancel()
            release.countDown()
            withTimeout(2_000) { pending.join() }
            awaitIdle()
            assertTrue(closed.await(2, TimeUnit.SECONDS))
            assertTrue("Late response must not write routes, identity or credentials", memory.isEmpty())
            assertTrue(calls.single().isCanceled())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `large valid JSON prefix is rejected before reading the entire response`() = runBlocking {
        val read = AtomicLong()
        respond = { response(it.request(), trackedBody(payload + " ".repeat(1024 * 1024), read = read)) }
        val failure = runCatching { register() }.exceptionOrNull()
        assertNotNull("Oversize cannot become a successful enrollment", failure)
        assertTrue("Only the size probe plus one Okio segment may be read", read.get() <= 65_537 + 8_192)
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertTrue(memory.isEmpty())
    }

    @Test fun `known HTTP failure does not wait for an unbounded error body`() = runBlocking {
        respond = { entered.countDown(); response(it.request(), trackedBody(hold = true), 503) }
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            awaitEntered()
            val failure = withTimeoutOrNull(1_000) { pending.await() }
            assertTrue("HTTP status must remain available without draining its body", failure is RegistrationException)
            assertEquals(503, (failure as RegistrationException).httpCode)
            assertTrue(closed.await(2, TimeUnit.SECONDS))
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `malformed response closes body and preserves stored state`() = runBlocking {
        store.saveApiKey("existing-key")
        val before = memory.toMap()
        respond = { response(it.request(), trackedBody("{")) }
        assertNotNull(runCatching { register() }.exceptionOrNull())
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertEquals(before, memory)
    }

    @Test fun `successful registration retains explicit routes and issued credentials`() = runBlocking {
        respond = { response(it.request(), trackedBody()) }
        assertEquals(id, register(withFallback = true).deviceId)
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
        assertEquals(backup, memory["fallback_server_url"])
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertFalse(calls.single().isCanceled())
    }

    @Test fun `HTTP deadline also covers a stalled success body`() = runBlocking {
        respond = { response(it.request(), trackedBody(hold = true)) }
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            awaitEntered()
            assertTrue(withTimeoutOrNull(12_000) { pending.await() } is IOException)
            assertTrue(calls.single().isCanceled())
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        assertTrue(memory.isEmpty())
    }

    @Test fun `cancelled late reply preserves credentials installed by a new owner`() = runBlocking {
        respond = { response(it.request(), trackedBody(hold = true)) }
        val pending = launch(Dispatchers.Default) { register() }
        try {
            awaitEntered()
            pending.cancel()
            store.saveServerRoutes(backup, url)
            store.saveDeviceId("22222222-2222-4222-8222-222222222222")
            store.saveTokens("new-owner-access", "new-owner-refresh", 900)
            val before = memory.toMap()
            release.countDown()
            pending.join()
            awaitIdle()
            assertEquals(before, memory)
            assertTrue(closed.await(2, TimeUnit.SECONDS))
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `valid body at exactly 64 KiB remains supported`() = runBlocking {
        val body = payload + " ".repeat(65_536 - payload.toByteArray(Charsets.UTF_8).size)
        respond = { response(it.request(), trackedBody(body)) }
        assertEquals(id, register().deviceId)
        assertEquals("issued-access", store.getToken())
        assertTrue(closed.await(2, TimeUnit.SECONDS))
    }

    @Test fun `transport failure preserves prior state and later registration can succeed`() = runBlocking {
        store.saveApiKey("existing-key")
        val before = memory.toMap()
        respond = { if (calls.size == 1) throw IOException("isolated connection failure") else response(it.request()) }
        assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
        assertEquals(before, memory)
        assertEquals(id, register().deviceId)
        assertEquals("issued-access", store.getToken())
        assertEquals(2, calls.size)
    }

    @Test fun `caller deadline propagates instead of becoming a registration result`() = runBlocking {
        holdHeaders()
        val returned = AtomicBoolean(false)
        val pending = async(Dispatchers.Default) {
            withTimeoutOrNull(1_000) { register(); returned.set(true) }
        }
        try {
            awaitEntered()
            assertNull(withTimeout(2_000) { pending.await() })
            assertFalse(returned.get())
            assertTrue(calls.single().isCanceled())
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `queued registration cancellation leaves the dispatcher owner intact`() = runBlocking {
        client.dispatcher.maxRequests = 1
        holdHeaders()
        val blocker = client.newCall(Request.Builder().url(url).build())
        blocker.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { error(e) }
            override fun onResponse(call: Call, response: Response) { response.close() }
        })
        val pending = launch(Dispatchers.Default) { register() }
        try {
            awaitEntered()
            withTimeout(3_000) { while (client.dispatcher.queuedCallsCount() != 1) delay(5) }
            val queued = client.dispatcher.queuedCalls().single()
            pending.cancel()
            assertEquals(true, withTimeoutOrNull(1_000) { pending.join(); true })
            assertTrue(queued.isCanceled())
            assertFalse(blocker.isCanceled())
            assertTrue(memory.isEmpty())
            release.countDown()
            awaitIdle()
            // An application interceptor can observe a cancelled call after queue
            // promotion; it is not evidence of a network send. Drain callbacks,
            // then verify cancellation and absence of any credential write.
            assertTrue(calls.contains(blocker))
        assertTrue(calls.all { it === blocker || it.isCanceled() })
            assertTrue(memory.isEmpty())
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `first registration uses configured backup after primary transport failure`() = runBlocking {
        respond = {
            if (it.request().url.host == "primary.invalid") throw IOException("primary connection refused")
            response(it.request())
        }
        assertEquals(backup, register(withFallback = true).serverUrl)
        assertEquals(listOf("primary.invalid", "backup.invalid"), calls.map { it.request().url.host })
        assertTrue(calls.all { it.request().header("X-API-Key") == "sphr_isolated" })
        assertEquals(backup, store.getServerUrl())
        assertEquals(url, memory["fallback_server_url"])
        assertEquals(id, store.getDeviceId())
        assertEquals("issued-access", store.getToken())
    }

    @Test fun `first registration uses backup after unavailable primary gateway`() = runBlocking {
        respond = { response(it.request(), code = if (it.request().url.host == "primary.invalid") 503 else 201) }
        assertEquals(backup, register(withFallback = true).serverUrl)
        assertEquals(2, calls.size)
        assertEquals("issued-refresh", memory["refresh_token"])
    }

    @Test fun `unavailable route pair leaves credentials intact after exactly two attempts`() = runBlocking {
        store.saveApiKey("existing-key")
        val before = memory.toMap()
        respond = { throw IOException("both management routes unavailable") }
        assertTrue(runCatching { register(withFallback = true) }.exceptionOrNull() is IOException)
        assertEquals(listOf("primary.invalid", "backup.invalid"), calls.map { it.request().url.host })
        assertEquals(before, memory)
    }

    @Test fun `credential rejection does not probe another route`() = runBlocking {
        respond = { response(it.request(), code = 401) }
        val failure = runCatching { register(withFallback = true) }.exceptionOrNull()
        assertEquals(401, (failure as RegistrationException).httpCode)
        assertEquals(1, calls.size)
        assertTrue(memory.isEmpty())
    }

    @Test fun `rate limit is returned for backoff rather than immediate alternate request`() = runBlocking {
        respond = { response(it.request(), code = 429) }
        val failure = runCatching { register(withFallback = true) }.exceptionOrNull()
        assertEquals(429, (failure as RegistrationException).httpCode)
        assertEquals(1, calls.size)
        assertTrue(memory.isEmpty())
    }

    @Test fun `equivalent configured route is not attempted twice`() = runBlocking {
        respond = { throw IOException("route unavailable") }
        assertTrue(runCatching {
            registration.register(url, "sphr_isolated", fallbackServerUrl = "$url/")
        }.exceptionOrNull() is IOException)
        assertEquals(1, calls.size)
    }
}
