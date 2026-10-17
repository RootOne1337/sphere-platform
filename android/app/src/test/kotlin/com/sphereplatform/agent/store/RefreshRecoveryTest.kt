package com.sphereplatform.agent.store

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import dagger.Lazy
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.IOException

/** Memory/disk are separate: apply may be lost on crash, commit must precede HTTP. */
class RefreshRecoveryTest {
    private val memory = mutableMapOf<String, Any?>()
    private val disk = mutableMapOf<String, Any?>()
    private val requests = mutableListOf<Request>()
    private lateinit var prefs: EncryptedSharedPreferences
    private lateinit var client: Lazy<OkHttpClient>
    private var diskHealthy = true
    private var respond: (Request) -> Response = { response(it) }

    private fun response(request: Request) = Response.Builder().request(request)
        .protocol(Protocol.HTTP_1_1).code(200).message("OK")
        .body("""{"access_token":"fresh-access","refresh_token":"child-refresh","expires_in":900}"""
            .toResponseBody("application/json".toMediaType())).build()

    @Before
    fun setup() {
        memory.putAll(mapOf("access_token" to "old-access", "refresh_token" to "parent-refresh",
            "access_token_expires_at" to 0L, "server_url" to "https://isolated.invalid"))
        disk.putAll(memory)
        prefs = mockk {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { getLong(any(), any()) } answers { memory[firstArg()] as? Long ?: secondArg() }
            every { edit() } answers {
                val pending = mutableMapOf<String, Any?>()
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { putLong(any(), any()) } answers { pending[firstArg()] = secondArg<Long>(); this@editor }
                    every { remove(any()) } answers { pending[firstArg()] = null; this@editor }
                    every { apply() } answers { memory.putAll(pending); Unit }
                    every { commit() } answers {
                        memory.putAll(pending)
                        if (diskHealthy) { disk.clear(); disk.putAll(memory) }
                        diskHealthy
                    }
                }
            }
        }
        val http = OkHttpClient.Builder().addInterceptor {
            requests.add(it.request())
            respond(it.request()) // No DNS/socket/server: only the HTTP boundary is replaced.
        }.build()
        client = Lazy { http }
    }

    private fun store() = AuthTokenStore(prefs, client)
    private fun restart() { memory.clear(); memory.putAll(disk) }

    @Test
    fun `intent reaches disk before the first HTTP side effect`() = runBlocking {
        respond = {
            val id = it.header("X-Refresh-Request-Id")
            assertNotNull("Refresh needs a persisted intent before sending", id)
            assertEquals(id, disk["refresh_rotation_id"])
            assertEquals("parent-refresh", disk["refresh_token"])
            response(it)
        }
        assertEquals("fresh-access", store().getFreshToken())
    }

    @Test
    fun `lost response retries original intent after process recreation`() = runBlocking {
        respond = { throw IOException("synthetic response loss") }
        assertEquals("old-access", store().getFreshToken())
        val id = requests.single().header("X-Refresh-Request-Id")
        assertNotNull(id)
        restart()
        respond = { response(it) }
        assertEquals("fresh-access", store().getFreshToken())
        assertEquals(id, requests.last().header("X-Refresh-Request-Id"))
        assertEquals("refresh_token=parent-refresh", requests.last().header("Cookie"))
    }

    @Test
    fun `crash before response apply reaches disk keeps recoverable parent intent`() = runBlocking {
        assertEquals("fresh-access", store().getFreshToken())
        val id = requests.single().header("X-Refresh-Request-Id")
        assertNotNull(id)
        assertEquals("child-refresh", memory["refresh_token"])
        assertEquals("parent-refresh", disk["refresh_token"])
        restart()
        assertEquals("fresh-access", store().getFreshToken())
        assertEquals(id, requests.last().header("X-Refresh-Request-Id"))
        assertEquals("refresh_token=parent-refresh", requests.last().header("Cookie"))
    }

    @Test
    fun `next rotation persists child before consuming it and uses new intent`() = runBlocking {
        val store = store()
        store.getFreshToken()
        val first = requests.single().header("X-Refresh-Request-Id")
        assertNotNull(first)
        store.clearTokenCache()
        respond = {
            assertEquals("child-refresh", disk["refresh_token"])
            assertEquals(it.header("X-Refresh-Request-Id"), disk["refresh_rotation_id"])
            assertNotEquals(first, it.header("X-Refresh-Request-Id"))
            response(it)
        }
        store.getFreshToken()
        assertEquals(2, requests.size)
    }

    @Test
    fun `failed intent commit never sends refresh even on repeated attempt`() = runBlocking {
        diskHealthy = false
        val store = store()
        repeat(2) { assertEquals("old-access", store.getFreshToken()) }
        assertEquals(0, requests.size)
        diskHealthy = true
        assertEquals("fresh-access", store.getFreshToken())
        assertEquals(1, requests.size)
    }

    @Test
    fun `reenrollment while refresh is in flight cannot be overwritten by stale reply`() = runBlocking {
        val store = store()
        respond = {
            store.saveTokens("reenrolled-access", "reenrolled-refresh", 900)
            response(it)
        }
        assertEquals("reenrolled-access", store.getFreshToken())
        assertEquals("reenrolled-refresh", memory["refresh_token"])
    }

    @Test
    fun `clearing credentials while refresh is in flight cannot restore them`() = runBlocking {
        val store = store()
        respond = { store.clearTokens(); response(it) }
        assertNull(store.getFreshToken())
        assertNull(memory["refresh_token"])
    }
}
