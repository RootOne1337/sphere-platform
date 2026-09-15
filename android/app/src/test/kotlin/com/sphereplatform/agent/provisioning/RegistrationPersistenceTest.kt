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
import okhttp3.ResponseBody.Companion.toResponseBody
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
import java.util.concurrent.atomic.AtomicInteger

/** Real client/store with separate preference memory/disk and isolated HTTP issuance gates. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class RegistrationPersistenceTest {
    private val primary = "https://primary.invalid"
    private val backup = "https://backup.invalid"
    private val oldUrl = "https://old.invalid"
    private val oldId = "11111111-1111-4111-8111-111111111111"
    private val id = "22222222-2222-4222-8222-222222222222"
    private val memory = ConcurrentHashMap<String, Any>()
    private val disk = ConcurrentHashMap<String, Any>()
    private val snapshots = CopyOnWriteArrayList<Map<String, Any>>()
    private val requests = CopyOnWriteArrayList<Request>()
    private val sequence = AtomicInteger()
    private val entered = CountDownLatch(1)
    private val release = CountDownLatch(1)
    private val commitEntered = CountDownLatch(1)
    private val commitRelease = CountDownLatch(1)
    private var holdCredentialCommit = false
    private var failCredentialCommit = false
    private var throwCredentialCommit = false
    private var stopAfterRouteCommit = false
    private var holdFirstReply = false
    private var replyId = id
    private var accessJson: String? = null
    private var refreshJson: String? = null
    private var expiresIn = 900L
    private var status = 201
    private lateinit var prefs: EncryptedSharedPreferences
    private lateinit var client: OkHttpClient
    private lateinit var store: AuthTokenStore
    private lateinit var registration: DeviceRegistrationClient

    @Before fun setup() {
        prefs = mockk {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { getLong(any(), any()) } answers { memory[firstArg()] as? Long ?: secondArg() }
            every { contains(any()) } answers { memory.containsKey(firstArg()) }
            every { edit() } answers {
                val pending = mutableMapOf<String, Any?>()
                fun applyChanges() = pending.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { putLong(any(), any()) } answers { pending[firstArg()] = secondArg<Long>(); this@editor }
                    every { remove(any()) } answers { pending[firstArg()] = null; this@editor }
                    every { apply() } answers { applyChanges() }
                    every { commit() } answers {
                        applyChanges()
                        if (holdCredentialCommit && "access_token" in pending) {
                            commitEntered.countDown()
                            check(commitRelease.await(15, TimeUnit.SECONDS))
                        }
                        if (throwCredentialCommit && "access_token" in pending) throw IOException("isolated disk error")
                        if (failCredentialCommit && "access_token" in pending) {
                            false // Android may expose memory even though disk persistence failed.
                        } else {
                            disk.clear(); disk.putAll(memory)
                            snapshots.add(disk.toMap())
                            if (stopAfterRouteCommit && "server_url" in pending && "access_token" !in pending) {
                                throw IOException("isolated stop after route-only disk write")
                            }
                            true
                        }
                    }
                }
            }
        }
        client = OkHttpClient.Builder().addInterceptor { chain ->
            requests.add(chain.request())
            val issued = sequence.incrementAndGet()
            if (holdFirstReply && issued == 1) {
                entered.countDown()
                check(release.await(15, TimeUnit.SECONDS))
            }
            val access = accessJson ?: "\"access-$issued\""
            val refresh = refreshJson ?: "\"refresh-$issued\""
            val body = """{"device_id":"$replyId","name":"isolated","access_token":$access,
                "refresh_token":$refresh,"expires_in":$expiresIn,"server_url":"$primary","is_new":true}"""
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(status).message("isolated").body(body.toResponseBody()).build()
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
        commitRelease.countDown()
        client.dispatcher.executorService.shutdown()
        assertTrue(client.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        client.connectionPool.evictAll()
    }

    private suspend fun register() = registration.register(primary, "sphr_isolated", fallbackServerUrl = backup)
    private suspend fun awaitIdle() = withTimeout(5_000) {
        while (client.dispatcher.runningCallsCount() != 0 || client.dispatcher.queuedCallsCount() != 0) delay(5)
    }
    private fun seedOldIdentity() {
        memory.putAll(mapOf("server_url" to oldUrl, "primary_server_url" to oldUrl,
            "device_id" to oldId, "access_token" to "old-access", "refresh_token" to "old-refresh",
            "access_token_expires_at" to 0L, "refresh_rotation_id" to "old-intent"))
        disk.putAll(memory)
    }

    @Test fun `successful registration survives losing all pending apply writes`() = runBlocking {
        register()
        assertEquals("access-1", store.getToken())
        memory.clear(); memory.putAll(disk)
        val recreated = AuthTokenStore(prefs, Lazy { client })
        assertEquals("Registration success must mean durable credentials", "access-1", recreated.getToken())
        assertEquals(id, recreated.getDeviceId())
        assertEquals(primary, recreated.getServerUrl())
        assertEquals(backup, disk["fallback_server_url"])
    }

    @Test fun `credential disk failure cannot report successful enrollment`() = runBlocking {
        seedOldIdentity()
        val before = disk.toMap()
        failCredentialCommit = true
        assertTrue("A failed credential commit must reach the caller", runCatching { register() }.exceptionOrNull() is IOException)
        assertEquals(before, disk)
        assertEquals("Failed commit must not publish new in-memory credentials", before, memory)
    }

    @Test fun `stop at a preference boundary never leaves new routes with old identity`() = runBlocking {
        seedOldIdentity()
        stopAfterRouteCommit = true
        runCatching { register() }
        assertTrue(snapshots.isNotEmpty())
        for (snapshot in snapshots) {
            val coherentOld = snapshot["server_url"] == oldUrl && snapshot["device_id"] == oldId && snapshot["access_token"] == "old-access"
            val coherentNew = snapshot["server_url"] == primary && snapshot["device_id"] == id && snapshot["access_token"] == "access-1"
            assertTrue("Persisted boundary must contain one complete identity: $snapshot", coherentOld || coherentNew)
        }
    }

    @Test fun `clear during registration cannot be undone by its late reply`() = runBlocking {
        seedOldIdentity()
        holdFirstReply = true
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            store.clearTokens()
            val cleared = memory.toMap()
            release.countDown()
            assertTrue(pending.await() is IOException)
            assertEquals(cleared, memory)
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `local route change wins over an earlier registration reply`() = runBlocking {
        seedOldIdentity()
        holdFirstReply = true
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            store.saveServerRoutes(backup, oldUrl)
            val selected = memory.toMap()
            release.countDown()
            assertTrue(pending.await() is IOException)
            assertEquals(selected, memory)
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `overlapping registration calls cannot install replies in reverse issuance order`() = runBlocking {
        holdFirstReply = true
        val first = async(Dispatchers.Default) { register() }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val second = async(Dispatchers.Default) { register() }
        try {
            // Baseline lets the second issuance finish while the first reply is held.
            // The repaired client keeps it pending until the first local commit ends.
            assertNull(withTimeoutOrNull(1_000) { second.await() })
            assertEquals(1, requests.size)
        } finally {
            release.countDown()
            withTimeout(5_000) { awaitAll(first, second) }
            awaitIdle()
        }
        assertEquals("access-2", store.getToken())
        assertEquals("refresh-2", disk["refresh_token"])
    }

    @Test fun `invalid assigned UUID is rejected before changing storage`() = runBlocking {
        seedOldIdentity()
        val before = memory.toMap()
        replyId = "not-a-uuid"
        assertNotNull(runCatching { register() }.exceptionOrNull())
        assertEquals(before, memory)
        assertEquals(before, disk)
    }

    @Test fun `JSON null access token is rejected instead of being persisted as text`() = runBlocking {
        accessJson = "null"
        assertNotNull(runCatching { register() }.exceptionOrNull())
        assertTrue(memory.isEmpty())
        assertTrue(disk.isEmpty())
    }

    @Test fun `HTTP denial preserves the previous complete identity`() = runBlocking {
        seedOldIdentity()
        val before = memory.toMap()
        status = 401
        val failure = runCatching { register() }.exceptionOrNull()
        assertEquals(401, (failure as RegistrationException).httpCode)
        assertEquals(before, memory)
        assertEquals(before, disk)
    }

    @Test fun `failed first commit restores absent keys and explicit retry can succeed`() = runBlocking {
        failCredentialCommit = true
        assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
        assertTrue(memory.isEmpty())
        assertTrue(disk.isEmpty())
        failCredentialCommit = false
        register()
        assertEquals("access-2", disk["access_token"])
        assertEquals(id, disk["device_id"])
    }

    @Test fun `throwing storage restores full old memory and releases registration lock`() = runBlocking {
        seedOldIdentity()
        val before = memory.toMap()
        throwCredentialCommit = true
        assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
        assertEquals(before, memory)
        assertEquals(before, disk)
        throwCredentialCommit = false
        withTimeout(5_000) { register() }
        assertEquals("refresh-2", disk["refresh_token"])
        assertFalse(disk.containsKey("refresh_rotation_id"))
    }

    @Test fun `clearing then restoring identical tokens still invalidates earlier response`() = runBlocking {
        seedOldIdentity()
        holdFirstReply = true
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            store.clearTokens()
            store.saveTokens("old-access", "old-refresh", 900)
            val newer = memory.toMap()
            release.countDown()
            assertTrue(pending.await() is IOException)
            assertEquals(newer, memory)
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `identity replacement fences reply even when credentials and URL are unchanged`() = runBlocking {
        seedOldIdentity()
        holdFirstReply = true
        val pending = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            store.saveDeviceId("33333333-3333-4333-8333-333333333333")
            val newer = memory.toMap()
            release.countDown()
            assertTrue(pending.await() is IOException)
            assertEquals(newer, memory)
        } finally { release.countDown(); pending.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `cancelled registration waiter leaves owner alive and sends no second request`() = runBlocking {
        holdFirstReply = true
        val first = async(Dispatchers.Default) { register() }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val waiting = async(Dispatchers.Default) { register() }
        try {
            assertNull(withTimeoutOrNull(200) { waiting.await() })
            withTimeout(1_000) { waiting.cancelAndJoin() }
            assertFalse(first.isCompleted)
            assertEquals(1, requests.size)
            release.countDown()
            withTimeout(5_000) { first.await() }
            assertEquals("access-1", disk["access_token"])
            withTimeout(5_000) { register() }
            assertEquals("access-2", disk["access_token"])
        } finally { release.countDown(); waiting.cancelAndJoin(); first.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `registration waits for earlier refresh before issuing replacement credentials`() = runBlocking {
        seedOldIdentity()
        memory.remove("refresh_rotation_id")
        holdFirstReply = true
        val refresh = async(Dispatchers.Default) { store.getFreshToken() }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val enroll = async(Dispatchers.Default) { register() }
        try {
            assertNull(withTimeoutOrNull(200) { enroll.await() })
            assertEquals(1, requests.size)
            release.countDown()
            withTimeout(5_000) { refresh.await(); enroll.await() }
            assertEquals(listOf("/api/v1/devices/refresh", "/api/v1/devices/register"), requests.map { it.url.encodedPath })
            assertEquals("access-2", store.getToken())
            assertEquals("refresh-2", disk["refresh_token"])
        } finally { release.countDown(); enroll.cancelAndJoin(); refresh.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `token reader waits for registration instead of rotating previous credentials`() = runBlocking {
        seedOldIdentity()
        holdFirstReply = true
        val enroll = async(Dispatchers.Default) { register() }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val refresh = async(Dispatchers.Default) { store.getFreshToken() }
        try {
            assertNull(withTimeoutOrNull(200) { refresh.await() })
            assertEquals(1, requests.size)
            release.countDown()
            withTimeout(5_000) { enroll.await(); assertEquals("access-1", refresh.await()) }
            assertEquals(1, requests.size)
        } finally { release.countDown(); enroll.cancelAndJoin(); refresh.cancelAndJoin(); awaitIdle() }
    }

    @Test fun `non-string and blank credentials never mutate an installed identity`() = runBlocking {
        seedOldIdentity()
        val before = memory.toMap()
        for (invalid in listOf("null", "123", "true", "\"\"", "\"  \"")) {
            accessJson = invalid
            assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
            accessJson = null
            refreshJson = invalid
            assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
            refreshJson = null
            assertEquals(before, memory)
            assertEquals(before, disk)
        }
    }

    @Test fun `nonpositive and overflowing expiry never mutate registration state`() = runBlocking {
        for (invalid in listOf(0L, -1L, Long.MAX_VALUE, Long.MAX_VALUE / 1000)) {
            expiresIn = invalid
            assertTrue(runCatching { register() }.exceptionOrNull() is IOException)
            assertTrue(memory.isEmpty())
            assertTrue(disk.isEmpty())
        }
    }

    @Test fun `same-route registration invalidates previously captured WS route plan`() = runBlocking {
        store.saveServerRoutes(primary, backup)
        val before = store.connectionRoutesSnapshot()
        register()
        assertFalse(store.acceptConnectionRoute(before, primary))
        assertTrue(store.acceptConnectionRoute(store.connectionRoutesSnapshot(), primary))
    }

    @Test fun `failed commit candidate is never published to token readers`() = runBlocking {
        seedOldIdentity()
        holdCredentialCommit = true
        failCredentialCommit = true
        val enroll = async(Dispatchers.Default) { runCatching { register() }.exceptionOrNull() }
        assertTrue(commitEntered.await(5, TimeUnit.SECONDS))
        val reader = async(Dispatchers.Default) { store.getToken() }
        try {
            assertEquals("access-1", memory["access_token"])
            assertNull(withTimeoutOrNull(200) { reader.await() })
            commitRelease.countDown()
            withTimeout(5_000) {
                assertTrue(enroll.await() is IOException)
                assertEquals("old-access", reader.await())
            }
        } finally { commitRelease.countDown(); enroll.cancelAndJoin(); reader.cancelAndJoin(); awaitIdle() }
    }
}
