package com.sphereplatform.agent.store

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import dagger.Lazy
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.BufferedSource
import okio.ForwardingSource
import okio.Source
import okio.Timeout
import okio.buffer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Real OkHttp calls, synthetic interceptors/bodies: no DNS, listeners or external services. */
class RefreshCancellationTest {
    private val memory = ConcurrentHashMap<String, Any>()
    private val calls = CopyOnWriteArrayList<Call>()
    private val requests = CopyOnWriteArrayList<Request>()
    private val entered = CountDownLatch(1)
    private val release = CountDownLatch(1)
    private lateinit var client: OkHttpClient
    private lateinit var store: AuthTokenStore
    private var respond: (Interceptor.Chain) -> Response = { response(it.request()) }

    private val payload = """{"access_token":"fresh-access","refresh_token":"child-refresh","expires_in":900}"""

    private fun response(request: Request, body: ResponseBody = payload.toResponseBody()) =
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(200).message("OK").body(body).build()

    @Before
    fun setup() {
        memory.putAll(mapOf("access_token" to "old-access", "refresh_token" to "parent-refresh",
            "access_token_expires_at" to 0L, "server_url" to "https://isolated.invalid"))
        val prefs = mockk<EncryptedSharedPreferences> {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { getLong(any(), any()) } answers { memory[firstArg()] as? Long ?: secondArg() }
            every { edit() } answers {
                val pending = mutableMapOf<String, Any?>()
                fun applyChanges() = pending.forEach { (key, value) ->
                    if (value == null) memory.remove(key) else memory[key] = value
                }
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { putLong(any(), any()) } answers { pending[firstArg()] = secondArg<Long>(); this@editor }
                    every { remove(any()) } answers { pending[firstArg()] = null; this@editor }
                    every { apply() } answers { applyChanges() }
                    every { commit() } answers { applyChanges(); true }
                }
            }
        }
        client = OkHttpClient.Builder().addInterceptor { chain ->
            calls.add(chain.call())
            requests.add(chain.request())
            respond(chain)
        }.build()
        store = AuthTokenStore(prefs, Lazy { client })
    }

    @After
    fun cleanup() {
        release.countDown()
        client.dispatcher.executorService.shutdown()
        assertTrue("HTTP test threads must finish", client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        client.connectionPool.evictAll()
    }

    private fun holdFirstHeaders() {
        respond = {
            if (requests.size == 1) {
                entered.countDown()
                check(release.await(20, TimeUnit.SECONDS)) { "Test failed to release headers" }
            }
            response(it.request())
        }
    }

    private fun awaitEntered() = assertTrue("Refresh must reach HTTP", entered.await(5, TimeUnit.SECONDS))

    @Test
    fun `ten second deadline cancels HTTP and lets next refresh recover original intent`() = runBlocking {
        holdFirstHeaders()
        val refresh = async(Dispatchers.Default) { store.getFreshToken() }
        try {
            awaitEntered()
            val id = requests.single().header("X-Refresh-Request-Id")
            val result = withTimeoutOrNull(12_000) { refresh.await() }
            assertEquals("Refresh must release its mutex at the deadline while HTTP is still stuck", "old-access", result)
            assertTrue("Deadline must cancel the actual OkHttp Call", calls.first().isCanceled())
            assertEquals("parent-refresh", memory["refresh_token"])
            assertEquals(id, memory["refresh_rotation_id"])
            assertEquals("fresh-access", withTimeout(2_000) { store.getFreshToken() })
            assertEquals(id, requests.last().header("X-Refresh-Request-Id"))
            assertEquals("refresh_token=parent-refresh", requests.last().header("Cookie"))
        } finally {
            release.countDown()
            refresh.cancelAndJoin()
        }
    }

    @Test
    fun `stopping caller cancels HTTP and finishes without waiting for headers`() = runBlocking {
        holdFirstHeaders()
        val returned = AtomicBoolean(false)
        val refresh = launch(Dispatchers.Default) { store.getFreshToken(); returned.set(true) }
        try {
            awaitEntered()
            refresh.cancel()
            assertEquals("Stop must not wait for the server", true, withTimeoutOrNull(1_000) { refresh.join(); true })
            assertTrue(calls.single().isCanceled())
            assertFalse("Caller cancellation must propagate", returned.get())
            assertEquals("parent-refresh", memory["refresh_token"])
            assertNotNull(memory["refresh_rotation_id"])
        } finally {
            release.countDown()
            refresh.cancelAndJoin()
        }
    }

    @Test
    fun `cancelled body read closes late response without changing credentials`() = runBlocking {
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
            override fun contentType() = "application/json".toMediaType()
            override fun contentLength() = -1L
            override fun source(): BufferedSource = source
        }
        respond = { response(it.request(), body) }
        val refresh = launch(Dispatchers.Default) { store.getFreshToken() }
        try {
            awaitEntered()
            refresh.cancel()
            // Let the body arrive AFTER cancellation, even if the transport ignores cancel.
            release.countDown()
            withTimeout(2_000) { refresh.join() }
            assertTrue("Response body must be closed", closed.await(2, TimeUnit.SECONDS))
            assertEquals("Late body must not rotate credentials", "parent-refresh", memory["refresh_token"])
            assertEquals("old-access", store.getToken())
            assertNotNull(memory["refresh_rotation_id"])
            assertTrue(calls.single().isCanceled())
        } finally {
            release.countDown()
            refresh.cancelAndJoin()
        }
    }

    @Test
    fun `caller deadline is not converted into a successful token fallback`() = runBlocking {
        holdFirstHeaders()
        val returned = AtomicBoolean(false)
        val refresh = async(Dispatchers.Default) {
            withTimeoutOrNull(1_000) { store.getFreshToken(); returned.set(true) }
        }
        try {
            awaitEntered()
            delay(1_100)
            release.countDown()
            assertNull(withTimeout(2_000) { refresh.await() })
            assertFalse("Cancelled caller must not continue after getFreshToken", returned.get())
        } finally {
            release.countDown()
            refresh.cancelAndJoin()
        }
    }

    @Test
    fun `cancelling a mutex waiter leaves the active refresh and other callers intact`() = runBlocking {
        holdFirstHeaders()
        val first = async(Dispatchers.Default) { store.getFreshToken() }
        try {
            awaitEntered()
            val waiter = launch(start = CoroutineStart.UNDISPATCHED) { store.getFreshToken() }
            waiter.cancelAndJoin()
            assertFalse(calls.single().isCanceled())
            val fleet = List(64) { async(start = CoroutineStart.UNDISPATCHED) { store.getFreshToken() } }
            release.countDown()
            assertEquals("fresh-access", first.await())
            assertTrue(fleet.awaitAll().all { it == "fresh-access" })
            assertEquals("Concurrent callers must share one refresh", 1, requests.size)
        } finally {
            release.countDown()
            first.cancelAndJoin()
        }
    }

    private fun assertRejectedBodyRetryable(content: String) = runBlocking {
        val closed = AtomicBoolean(false)
        val source = object : ForwardingSource(Buffer().writeUtf8(content)) {
            override fun close() { closed.set(true); super.close() }
        }.buffer()
        val body = object : ResponseBody() {
            override fun contentType() = "application/json".toMediaType()
            override fun contentLength() = -1L
            override fun source(): BufferedSource = source
        }
        respond = { if (requests.size == 1) response(it.request(), body) else response(it.request()) }
        assertEquals("old-access", withTimeout(2_000) { store.getFreshToken() })
        assertTrue("Rejected body must be closed", closed.get())
        assertEquals("parent-refresh", memory["refresh_token"])
        val id = requests.single().header("X-Refresh-Request-Id")
        assertNotNull(id)
        assertEquals(id, memory["refresh_rotation_id"])
        assertEquals("fresh-access", withTimeout(2_000) { store.getFreshToken() })
        assertEquals(id, requests.last().header("X-Refresh-Request-Id"))
    }

    @Test
    fun `malformed JSON from callback preserves retry and closes body`() = assertRejectedBodyRetryable("{")

    @Test
    fun `oversized callback response preserves retry and closes body`() = assertRejectedBodyRetryable("x".repeat(65_537))

    @Test
    fun `missing rotation token preserves retry and closes body`() =
        assertRejectedBodyRetryable("""{"access_token":"fresh-access","expires_in":900}""")
}
