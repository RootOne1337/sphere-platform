package com.sphereplatform.agent.ws

import android.content.SharedPreferences
import android.content.Context
import android.content.RestrictionsManager
import android.os.Bundle
import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.provisioning.CloneDetector
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.service.ConfigWatchdog
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.network.forManagementRoute
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
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import java.io.File
import java.nio.file.Files

/** Real store/provisioner/reconnect loop; HTTP and WS transport are isolated doubles. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class SavedRouteFailoverTest {
    private val primary = "https://primary.invalid"
    private val secondary = "https://secondary.invalid"
    private val device = "11111111-1111-4111-8111-111111111111"
    private val memory = ConcurrentHashMap<String, Any>()
    private val disk = ConcurrentHashMap<String, Any>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val attempts = CopyOnWriteArrayList<Attempt>()
    private val requests = CopyOnWriteArrayList<Request>()
    private lateinit var realHttp: OkHttpClient
    private lateinit var http: OkHttpClient
    private lateinit var prefs: EncryptedSharedPreferences
    private lateinit var store: AuthTokenStore
    private lateinit var client: SphereWebSocketClient
    private lateinit var watchdog: ConfigWatchdog
    private var commitsSucceed = true
    private var applyPersists = false
    private var respond: (Request) -> Response = { response(it) }
    private var configPayload = """{"server_url":"$primary","fallback_server_url":"$secondary"}"""

    private data class Attempt(val request: Request, val socket: WebSocket, val listener: WebSocketListener)
    private fun response(request: Request, body: String = "{}", code: Int = 200) = Response.Builder()
        .request(request).protocol(Protocol.HTTP_1_1).code(code).message("isolated")
        .body(body.toResponseBody()).build()

    @Before
    fun setup() {
        memory.putAll(mapOf("server_url" to primary, "primary_server_url" to primary,
            "fallback_server_url" to secondary, "device_id" to device,
            "access_token" to "old-access", "refresh_token" to "parent-refresh",
            "access_token_expires_at" to Long.MAX_VALUE))
        disk.putAll(memory)
        prefs = mockk {
            every { getString(any(), any()) } answers { memory[firstArg()] as? String ?: secondArg() }
            every { getLong(any(), any()) } answers { memory[firstArg()] as? Long ?: secondArg() }
            every { edit() } answers {
                val pending = mutableMapOf<String, Any?>()
                fun applyChanges() = pending.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }
                mockk<SharedPreferences.Editor> editor@ {
                    every { putString(any(), any()) } answers { pending[firstArg()] = secondArg(); this@editor }
                    every { putLong(any(), any()) } answers { pending[firstArg()] = secondArg<Long>(); this@editor }
                    every { remove(any()) } answers { pending[firstArg()] = null; this@editor }
                    every { apply() } answers {
                        applyChanges()
                        if (applyPersists) { disk.clear(); disk.putAll(memory) }
                    }
                    every { commit() } answers {
                        applyChanges()
                        if (commitsSucceed) { disk.clear(); disk.putAll(memory) }
                        commitsSucceed
                    }
                }
            }
        }
        realHttp = OkHttpClient.Builder().addInterceptor { chain ->
            requests.add(chain.request())
            if (chain.request().url.host == "config.invalid") response(chain.request(), configPayload)
            else respond(chain.request())
        }.build()
        http = mockk(relaxed = true)
        val builder = mockk<OkHttpClient.Builder> {
            every { followRedirects(any()) } returns this
            every { followSslRedirects(any()) } returns this
            every { certificatePinner(any()) } returns this
            every { build() } answers { http }
        }
        every { http.certificatePinner } returns CertificatePinner.DEFAULT
        every { http.newBuilder() } returns builder
        every { http.newCall(any()) } answers { realHttp.newCall(firstArg()) }
        every { http.newWebSocket(any(), any()) } answers {
            val socket = mockk<WebSocket>(relaxed = true) { every { send(any<String>()) } returns true }
            attempts.add(Attempt(firstArg(), socket, secondArg()))
            socket
        }
        store = AuthTokenStore(prefs, Lazy { http })
        client = SphereWebSocketClient(http, store, Json)
        watchdog = ConfigWatchdog(ZeroTouchProvisioner(mockk(relaxed = true), "https://config.invalid/config") { realHttp }, store, client, scope)
    }

    @After
    fun cleanup() = runBlocking {
        watchdog.stop()
        client.disconnect()
        scope.cancel()
        withTimeout(5_000) { scope.coroutineContext[Job]!!.join() }
        realHttp.dispatcher.executorService.shutdown()
        assertTrue(realHttp.dispatcher.executorService.awaitTermination(5, TimeUnit.SECONDS))
        realHttp.connectionPool.evictAll()
    }

    private fun start() = scope.launch { client.connect(device) }
    private suspend fun attempt(index: Int): Attempt = withTimeout(5_000) {
        while (attempts.size <= index) delay(10)
        attempts[index]
    }
    private fun fail(a: Attempt) = a.listener.onFailure(a.socket, IOException("isolated primary outage"), null)
    private fun open(a: Attempt) = a.listener.onOpen(a.socket, response(a.request))
    private fun acknowledge(a: Attempt, id: String = device) = a.listener.onMessage(a.socket,
        """{"type":"auth_ok","device_id":"$id","protocol_version":1}""")
    private suspend fun settleConfig() = withTimeout(3_000) {
        // Used before starting the long-running WS loop.
        scope.coroutineContext[Job]!!.children.toList().joinAll()
    }

    @Test
    fun `saved secondary is attempted after primary network failure without discovery`() = runBlocking {
        start()
        val first = attempt(0)
        assertEquals("primary.invalid", first.request.url.host)
        fail(first)
        val backup = attempt(1)
        assertEquals("secondary.invalid", backup.request.url.host)
        assertEquals(primary, store.getServerUrl())
        open(backup)
        assertFalse(client.isConnected)
        acknowledge(backup)
        assertTrue(client.isConnected)
        assertEquals(secondary, store.getServerUrl())
        assertEquals(device, store.getDeviceId())
        assertTrue(requests.isEmpty())
    }

    @Test
    fun `expired access refresh follows secondary and retains original retry intent`() = runBlocking {
        memory["access_token_expires_at"] = 0L
        respond = { request ->
            if (request.url.host == "primary.invalid") response(request, code = 503)
            else response(request, """{"access_token":"fresh-access","refresh_token":"child-refresh","expires_in":900}""")
        }
        start()
        fail(attempt(0))
        val backup = attempt(1)
        assertEquals("secondary.invalid", backup.request.url.host)
        assertEquals(listOf("primary.invalid", "secondary.invalid"), requests.map { it.url.host })
        assertEquals(1, requests.map { it.header("X-Refresh-Request-Id") }.distinct().size)
        assertEquals(listOf("refresh_token=parent-refresh", "refresh_token=parent-refresh"), requests.map { it.header("Cookie") })
        open(backup)
        verify { backup.socket.send("""{"token":"fresh-access"}""") }
        acknowledge(backup)
        assertEquals(secondary, store.getServerUrl())
        assertEquals(device, store.getDeviceId())
    }

    @Test
    fun `discovery saves candidate pair without overwriting last selected route`() = runBlocking {
        configPayload = """{"server_url":"https://candidate.invalid","fallback_server_url":"$secondary"}"""
        watchdog.forceCheck()
        settleConfig()
        assertEquals(primary, store.getServerUrl())
        assertEquals("https://candidate.invalid", disk["primary_server_url"])
        assertEquals(secondary, disk["fallback_server_url"])
    }

    @Test
    fun `config without fallback does not discard previously saved backup`() = runBlocking {
        configPayload = """{"server_url":"$primary"}"""
        watchdog.forceCheck()
        settleConfig()
        assertEquals(primary, store.getServerUrl())
        assertEquals(secondary, disk["fallback_server_url"])
    }

    @Test
    fun `registration keeps successful LAN route and saves advertised address as backup`() = runBlocking {
        respond = { response(it, """{"device_id":"$device","name":"isolated-device",
            "access_token":"registered-access","refresh_token":"registered-refresh","expires_in":900,
            "server_url":"$secondary","is_new":true}""") }
        val detector = mockk<CloneDetector>(relaxed = true) {
            every { getFingerprint() } returns "isolated-fingerprint"
            every { getDeviceType() } returns "android"
        }
        DeviceRegistrationClient(http, store, detector, Json).register(primary, "isolated-enrollment-key")
        assertEquals(primary, store.getServerUrl())
        assertEquals(primary, disk["primary_server_url"])
        assertEquals(secondary, disk["fallback_server_url"])
        assertEquals(device, store.getDeviceId())
    }

    @Test
    fun `static credential also uses saved secondary without refresh`() = runBlocking {
        memory.remove("refresh_token")
        start()
        fail(attempt(0))
        val backup = attempt(1)
        assertEquals("secondary.invalid", backup.request.url.host)
        open(backup)
        acknowledge(backup)
        assertTrue(client.isConnected)
        assertTrue(requests.isEmpty())
    }

    @Test
    fun `both failed routes retry original without deleting credentials or starting commands`() = runBlocking {
        var commands = 0
        client.onJsonMessage = { commands++ }
        start()
        fail(attempt(0))
        val backup = attempt(1)
        assertEquals("secondary.invalid", backup.request.url.host)
        fail(backup)
        val original = attempt(2)
        assertEquals("primary.invalid", original.request.url.host)
        assertEquals(primary, store.getServerUrl())
        assertEquals("parent-refresh", memory["refresh_token"])
        assertEquals(0, commands)
    }

    @Test
    fun `wrong device acknowledgement cannot promote backup and original is retried`() = runBlocking {
        start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup)
        acknowledge(backup, "22222222-2222-4222-8222-222222222222")
        assertFalse(client.isConnected)
        assertEquals(primary, store.getServerUrl())
        assertEquals("primary.invalid", attempt(2).request.url.host)
        assertEquals(device, store.getDeviceId())
    }

    @Test
    fun `local route change during backup handshake invalidates its acknowledgement`() = runBlocking {
        start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup)
        store.saveServerUrl("https://operator.invalid")
        acknowledge(backup)
        assertFalse(client.isConnected)
        assertEquals("https://operator.invalid", store.getServerUrl())
        assertEquals("operator.invalid", attempt(2).request.url.host)
    }

    @Test
    fun `disconnect before backup acknowledgement prevents promotion`() = runBlocking {
        val job = start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup)
        client.disconnect()
        acknowledge(backup)
        job.cancelAndJoin()
        assertFalse(client.isConnected)
        assertEquals(primary, store.getServerUrl())
        assertEquals(2, attempts.size)
    }

    @Test
    fun `working authenticated connection survives discovery change`() = runBlocking {
        start()
        val first = attempt(0)
        open(first)
        acknowledge(first)
        configPayload = """{"server_url":"https://unreachable.invalid","fallback_server_url":"$secondary"}"""
        watchdog.forceCheck()
        withTimeout(3_000) {
            while (disk["primary_server_url"] != "https://unreachable.invalid") delay(10)
        }
        assertTrue(client.isConnected)
        verify(exactly = 0) { first.socket.cancel() }
        assertEquals(primary, store.getServerUrl())
    }

    @Test
    fun `saved routes survive store recreation without discovery or applying last promotion`() = runBlocking {
        store.saveServerRoutes(primary, secondary)
        val job = start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup)
        acknowledge(backup)
        assertEquals(secondary, memory["server_url"])
        assertEquals(primary, disk["server_url"]) // apply() deliberately not persisted.
        job.cancelAndJoin()
        memory.clear(); memory.putAll(disk)
        store = AuthTokenStore(prefs, Lazy { http })
        client = SphereWebSocketClient(http, store, Json)
        attempts.clear()
        start()
        fail(attempt(0))
        assertEquals("secondary.invalid", attempt(1).request.url.host)
        assertEquals(device, store.getDeviceId())
    }

    @Test
    fun `persisted successful backup is first after recreation and can return to primary`() = runBlocking {
        applyPersists = true
        val job = start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup); acknowledge(backup)
        job.cancelAndJoin()
        memory.clear(); memory.putAll(disk)
        store = AuthTokenStore(prefs, Lazy { http })
        client = SphereWebSocketClient(http, store, Json)
        attempts.clear()
        start()
        val resumed = attempt(0)
        assertEquals("secondary.invalid", resumed.request.url.host)
        fail(resumed)
        val primaryAttempt = attempt(1)
        assertEquals("primary.invalid", primaryAttempt.request.url.host)
        open(primaryAttempt); acknowledge(primaryAttempt)
        assertEquals(primary, store.getServerUrl())
    }

    @Test
    fun `failed candidate commit does not replace either memory or durable routes`() = runBlocking {
        commitsSucceed = false
        configPayload = """{"server_url":"https://candidate.invalid","fallback_server_url":"https://other.invalid"}"""
        watchdog.forceCheck()
        settleConfig()
        assertEquals(primary, memory["server_url"])
        assertEquals(primary, memory["primary_server_url"])
        assertEquals(secondary, memory["fallback_server_url"])
        assertEquals(memory, disk)
    }

    @Test
    fun `legacy single route store keeps existing connection behavior`() = runBlocking {
        memory.remove("primary_server_url"); memory.remove("fallback_server_url")
        start()
        fail(attempt(0))
        val retried = attempt(1)
        assertEquals("primary.invalid", retried.request.url.host)
        open(retried); acknowledge(retried)
        assertTrue(client.isConnected)
        assertEquals(primary, store.getServerUrl())
    }

    @Test
    fun `route changes do not regenerate pending refresh intent`() = runBlocking {
        memory["access_token_expires_at"] = 0L
        memory["refresh_rotation_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        respond = { response(it, code = 503) }
        start()
        fail(attempt(0))
        attempt(1)
        assertEquals(2, requests.size)
        assertTrue(requests.all { it.header("X-Refresh-Request-Id") == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" })
        assertEquals("parent-refresh", memory["refresh_token"])
    }

    @Test
    fun `explicit provisioning replaces old fallback from a different installation`() {
        store.saveServerRoutes("https://new-installation.invalid")
        assertEquals("https://new-installation.invalid", disk["server_url"])
        assertNull(disk["fallback_server_url"])
        assertEquals(listOf("https://new-installation.invalid"), store.connectionRoutesSnapshot().urls)
    }

    @Test
    fun `invalid fallback rejects entire discovered plan`() = runBlocking {
        configPayload = """{"server_url":"https://candidate.invalid","fallback_server_url":"file:///bad"}"""
        watchdog.forceCheck()
        settleConfig()
        assertEquals(primary, store.getServerUrl())
        assertEquals(primary, memory["primary_server_url"])
        assertEquals(secondary, memory["fallback_server_url"])
    }

    @Test
    fun `configured pins extend to secondary without allowing redirect credential transfer`() {
        val pin = "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        val pinned = realHttp.newBuilder().certificatePinner(CertificatePinner.Builder().add("primary.invalid", pin).build()).build()
        val routed = pinned.forManagementRoute(secondary)
        assertFalse(routed.followRedirects)
        assertFalse(routed.followSslRedirects)
        assertEquals(listOf(pin), routed.certificatePinner.findMatchingPins("secondary.invalid").map { it.toString() })
        assertSame(pinned.dispatcher, routed.dispatcher)
        assertSame(pinned.connectionPool, routed.connectionPool)
    }

    @Test
    fun `already enrolled device reads route-only MDM config without HTTP or re-enrollment`() = runBlocking {
        val bundle = Bundle().apply {
            putString("sphere_server_url", primary)
            putString("sphere_fallback_server_url", "https://mdm-backup.invalid")
        }
        val context = mockk<Context>(relaxed = true) {
            every { getSystemService(Context.RESTRICTIONS_SERVICE) } returns mockk<RestrictionsManager> {
                every { applicationRestrictions } returns bundle
            }
        }
        val local = ConfigWatchdog(ZeroTouchProvisioner(context, "") { realHttp }, store, client, scope)
        local.run()
        assertEquals("https://mdm-backup.invalid", disk["fallback_server_url"])
        assertEquals(device, store.getDeviceId())
        assertEquals("parent-refresh", memory["refresh_token"])
        assertTrue(requests.isEmpty())
    }

    @Test
    fun `route-only local file config can be applied to enrolled device without GitHub`() = runBlocking {
        val dir = Files.createTempDirectory("sphere-route-test").toFile()
        val file = File(dir, "sphere-agent-config.json")
        file.writeText("""{"server_url":"$primary","fallback_server_url":"https://file-backup.invalid"}""")
        try {
            val context = mockk<Context>(relaxed = true) {
                every { getSystemService(Context.RESTRICTIONS_SERVICE) } returns null
                every { getExternalFilesDir(null) } returns dir
                every { filesDir } returns dir
            }
            val local = ConfigWatchdog(ZeroTouchProvisioner(context, "") { realHttp }, store, client, scope)
            local.run()
            assertEquals("https://file-backup.invalid", disk["fallback_server_url"])
            assertTrue(requests.isEmpty())
            assertEquals(device, store.getDeviceId())
        } finally {
            check(file.delete()); check(dir.delete())
        }
    }

    @Test
    fun `application connected callback observes promoted route and runs once`() = runBlocking {
        val observed = mutableListOf<String>()
        client.onConnected = { observed.add(store.getServerUrl()) }
        start()
        fail(attempt(0))
        val backup = attempt(1)
        open(backup); acknowledge(backup); acknowledge(backup)
        assertEquals(listOf(secondary), observed)
    }

    @Test
    fun `ended primary callbacks cannot replace promoted backup or deliver commands`() = runBlocking {
        var commands = 0
        client.onJsonMessage = { commands++ }
        start()
        val first = attempt(0)
        fail(first)
        val backup = attempt(1)
        open(backup); acknowledge(backup)
        open(first); acknowledge(first)
        first.listener.onMessage(first.socket, """{"type":"execute_dag","id":"stale"}""")
        assertEquals(secondary, store.getServerUrl())
        assertTrue(client.isConnected)
        assertEquals(0, commands)
    }

    @Test
    fun `invalid configured URL does not change either active or saved pair`() {
        assertThrows(IllegalArgumentException::class.java) { store.saveServerRoutes("https://user:password@bad.invalid", secondary) }
        assertEquals(primary, store.getServerUrl())
        assertEquals(secondary, disk["fallback_server_url"])
    }

    @Test
    fun `duplicate primary and fallback are normalized to one route`() {
        store.saveServerRoutes("https://PRIMARY.invalid/", "https://primary.invalid:443/")
        assertEquals(listOf(primary), store.connectionRoutesSnapshot().urls)
        assertNull(disk["fallback_server_url"])
    }

    @Test
    fun `auth denial advances to saved alternate without new enrollment`() = runBlocking {
        start()
        val first = attempt(0)
        open(first)
        first.listener.onClosed(first.socket, 4001, "invalid-token")
        respond = { response(it, """{"access_token":"fresh-access","refresh_token":"child-refresh","expires_in":900}""") }
        val backup = withTimeout(7_000) {
            while (attempts.size < 2) delay(10)
            attempts[1]
        }
        assertEquals("secondary.invalid", backup.request.url.host)
        assertEquals(listOf("secondary.invalid"), requests.map { it.url.host })
        open(backup); acknowledge(backup)
        assertTrue(client.isConnected)
        assertEquals(device, store.getDeviceId())
    }

    @Test
    fun `fleet generator enrollment key shape is accepted with saved fallback`() = runBlocking {
        val dir = Files.createTempDirectory("sphere-bootstrap-test").toFile()
        val file = File(dir, "sphere-agent-config.json")
        file.writeText("""{"config_version":1,"server_url":"$primary","fallback_server_url":"$secondary",
            "enrollment_api_key":"sphr_isolated"}""")
        try {
            val context = mockk<Context>(relaxed = true) {
                every { getSystemService(Context.RESTRICTIONS_SERVICE) } returns null
                every { getExternalFilesDir(null) } returns dir
                every { filesDir } returns dir
            }
            val result = ZeroTouchProvisioner(context, "") { realHttp }.discoverConfig()
            assertEquals(primary, result?.serverUrl)
            assertEquals(secondary, result?.fallbackServerUrl)
            assertEquals("sphr_isolated", result?.apiKey)
            assertTrue(requests.isEmpty())
        } finally {
            check(file.delete()); check(dir.delete())
        }
    }
}
