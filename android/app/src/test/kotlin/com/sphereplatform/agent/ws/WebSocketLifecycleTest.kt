package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.Json
import okhttp3.*
import org.junit.Assert.*
import org.junit.Test
import timber.log.Timber
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class WebSocketLifecycleTest {
    private val auth = mockk<AuthTokenStore>(relaxed = true) {
        every { getDeviceId() } returns "local-test-device"
        coEvery { getFreshTokenForRoute(any(), any()) } returns "test-token"
        every { connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(0, listOf("http://127.0.0.1:12345"))
        every { acceptConnectionRoute(any(), any()) } returns true
        every { getServerUrl() } returns "http://127.0.0.1:12345"
    }
    private val socket = mockk<WebSocket>(relaxed = true) {
        every { send(any<String>()) } returns true
        every { queueSize() } returns 0L
    }
    private lateinit var listener: WebSocketListener
    private val requests = mutableListOf<Request>()
    private val http: OkHttpClient = mockk<OkHttpClient> {
        val baseClient = this
        every { certificatePinner } returns CertificatePinner.DEFAULT
        every { newBuilder() } answers {
            mockk<OkHttpClient.Builder> {
                every { followRedirects(any()) } returns this
                every { followSslRedirects(any()) } returns this
                every { build() } returns baseClient
            }
        }
        every { newWebSocket(any(), any()) } answers {
            requests.add(firstArg<Request>())
            listener = secondArg()
            socket
        }
    }
    private val client = SphereWebSocketClient(http, auth, Json)

    private fun authenticateSocket() {
        listener.onOpen(socket, mockk(relaxed = true))
        listener.onMessage(socket, """{"type":"auth_ok","device_id":"local-test-device","protocol_version":1}""")
        assertTrue(client.isConnected)
    }

    @Test fun cleanServerCloseWaitsBeforeReconnect() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        runCurrent()
        listener.onClosed(socket, 1001, "server_restart")
        runCurrent()
        verify(exactly = 1) { http.newWebSocket(any(), any()) }
        advanceTimeBy(999)
        runCurrent()
        verify(exactly = 1) { http.newWebSocket(any(), any()) }
        advanceTimeBy(1002)
        runCurrent()
        verify(exactly = 2) { http.newWebSocket(any(), any()) }
        job.cancelAndJoin()
    }

    @Test fun cleanServerCloseWaitIsInterruptibleByStop() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        runCurrent()
        listener.onClosed(socket, 1000, "maintenance")
        runCurrent()
        client.disconnect()
        runCurrent()
        assertTrue(job.isCompleted)
        verify(exactly = 1) { http.newWebSocket(any(), any()) }
    }

    @Test fun reconnectDelaySamplesDoNotCollapseToOneFleetDeadline() {
        val method = SphereWebSocketClient::class.java.getDeclaredMethod("calculateBackoff", Int::class.javaPrimitiveType)
        method.isAccessible = true
        val delays = List(128) { method.invoke(client, 5) as Long }
        assertTrue(delays.all { it in 15_000L..30_000L })
        assertTrue("Every recovering device would use the same retry deadline", delays.toSet().size > 32)
    }

    @Test fun cancellationDuringHandshakeReleasesSocket() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        job.cancelAndJoin()
        verify(atLeast = 1) { socket.cancel() }
        assertFalse(client.isConnected)
    }

    @Test fun forcedReconnectClosesActiveTransport() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        runCurrent()
        client.forceReconnectNow()
        verify(atLeast = 1) { socket.cancel() }
        job.cancelAndJoin()
    }

    @Test fun abnormalCloseWithoutStatusFailsOverToNextSavedRoute() = runTest {
        every { auth.connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(
            0,
            listOf("http://primary.example", "http://fallback.example"),
        )
        val job = launch { client.connect() }
        try {
            runCurrent()
            assertTrue(requests.single().url.toString().startsWith("http://primary.example/"))
            authenticateSocket()
            runCurrent()

            listener.onClosed(socket, 1005, "")
            runCurrent()
            advanceTimeBy(2_001)
            runCurrent()

            assertEquals("A no-status close must rotate to the saved fallback", 2, requests.size)
            assertTrue(requests[1].url.toString().startsWith("http://fallback.example/"))
        } finally {
            job.cancelAndJoin()
        }
    }

    @Test fun explicitRouteSwitchCanBypassReconnectDebounce() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        runCurrent()

        client.forceReconnectNow()
        client.forceReconnectNow(bypassDebounce = true)

        verify(exactly = 2) { socket.cancel() }
        job.cancelAndJoin()
    }

    @Test fun closingHandshakeIsAcknowledged() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        listener.onClosing(socket, 1000, "server_shutdown")
        verify { socket.close(1000, "server_shutdown") }
        job.cancelAndJoin()
    }

    @Test fun failureAfterOpenUsesBackoff() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        runCurrent()
        listener.onFailure(socket, IOException("local network failure"), null)
        runCurrent()
        verify(exactly = 1) { http.newWebSocket(any(), any()) }
        advanceTimeBy(999)
        runCurrent()
        verify(exactly = 1) { http.newWebSocket(any(), any()) }
        advanceTimeBy(1002)
        runCurrent()
        verify(exactly = 2) { http.newWebSocket(any(), any()) }
        job.cancelAndJoin()
    }

    @Test fun websocketFailureLogsRedactedLifecycleEvidence() = runTest {
        every { auth.connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(
            0,
            listOf("http://primary.example", "http://fallback.example"),
        )
        val messages = mutableListOf<String>()
        val tree = object : Timber.Tree() {
            override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
                messages += message
            }
        }
        Timber.plant(tree)
        val job = launch { client.connect() }
        try {
            runCurrent()
            val response = Response.Builder()
                .request(requests.single())
                .protocol(Protocol.HTTP_1_1)
                .code(502)
                .message("Bad Gateway")
                .build()
            listener.onFailure(socket, IOException("private-route-marker"), response)
            runCurrent()

            val lifecycle = messages.singleOrNull { it.startsWith("ws_lifecycle ") }
            assertNotNull("A transport failure must produce a structured lifecycle record", lifecycle)
            assertTrue(lifecycle!!.contains("event=onFailure"))
            assertTrue(lifecycle.contains("phase=pre_auth"))
            assertTrue(lifecycle.contains("route_slot=0"))
            assertTrue(lifecycle.contains("route_count=2"))
            assertTrue(lifecycle.contains("response_code=502"))
            assertTrue(lifecycle.contains("error_type=IOException"))
            assertFalse(lifecycle.contains("primary.example"))
            assertFalse(lifecycle.contains("private-route-marker"))
            assertFalse(lifecycle.contains("test-token"))
        } finally {
            job.cancelAndJoin()
            Timber.uproot(tree)
        }
    }

    @Test fun websocketCloseLogsCodeAndAuthenticatedPhaseWithoutReason() = runTest {
        val messages = mutableListOf<String>()
        val tree = object : Timber.Tree() {
            override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
                messages += message
            }
        }
        Timber.plant(tree)
        val job = launch { client.connect() }
        try {
            runCurrent()
            authenticateSocket()
            listener.onClosed(socket, 1005, "private-close-reason")
            runCurrent()

            val lifecycle = messages.singleOrNull { it.startsWith("ws_lifecycle ") }
            assertNotNull("A WebSocket close must produce a structured lifecycle record", lifecycle)
            assertTrue(lifecycle!!.contains("event=onClosed"))
            assertTrue(lifecycle.contains("phase=authenticated"))
            assertTrue(lifecycle.contains("close_code=1005"))
            assertTrue(lifecycle.contains("reason_present=true"))
            assertFalse(lifecycle.contains("private-close-reason"))
            assertFalse(lifecycle.contains("test-token"))
            assertFalse(lifecycle.contains("127.0.0.1"))
        } finally {
            job.cancelAndJoin()
            Timber.uproot(tree)
        }
    }

    @Test fun videoBackpressureDoesNotFillOkHttpQueue() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        authenticateSocket()
        every { socket.queueSize() } returns 2L * 1024 * 1024
        assertFalse(client.sendBinary(ByteArray(1024)))
        verify(exactly = 0) { socket.send(any<okio.ByteString>()) }
        job.cancelAndJoin()
    }

    @Test fun handshakeTimeoutRetriesInsteadOfCancellingConnectLoop() = runTest {
        val job = launch { client.connect() }
        runCurrent()
        advanceTimeBy(22_001)
        runCurrent()
        assertTrue(job.isActive)
        verify(atLeast = 1) { socket.cancel() }
        verify(exactly = 2) { http.newWebSocket(any(), any()) }
        job.cancelAndJoin()
    }

    @Test fun shortAuthenticatedSessionsAccumulateFailureDebtUntilStableSession() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent()
            repeat(2) { index ->
                authenticateSocket()
                runCurrent()
                listener.onFailure(socket, IOException("unexpected end of stream"), null)
                runCurrent()
                val debt = SphereWebSocketClient::class.java.getDeclaredField("consecutiveFailures").apply { isAccessible = true }
                assertEquals(index + 1, debt.getInt(client))
                advanceTimeBy(4_001)
                runCurrent()
            }

            authenticateSocket()
            runCurrent()
            advanceTimeBy(60_001)
            runCurrent()
            val debt = SphereWebSocketClient::class.java.getDeclaredField("consecutiveFailures").apply { isAccessible = true }
            assertEquals("A full stable window ends the previous failure streak", 0, debt.getInt(client))

            listener.onFailure(socket, IOException("unexpected end of stream"), null)
            runCurrent()
            assertEquals("A new failure after a stable session starts a fresh streak", 1, debt.getInt(client))
        } finally { job.cancelAndJoin() }
    }

    @Test fun tcpOpenWithoutAuthenticationDoesNotResetFailureDebt() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent()
            repeat(2) { index ->
                listener.onOpen(socket, mockk(relaxed = true))
                runCurrent()
                assertFalse(client.isConnected)
                listener.onFailure(socket, IOException("lost before auth ack"), null)
                runCurrent()
                if (index == 0) { advanceTimeBy(2001); runCurrent() }
            }
            advanceTimeBy(1999); runCurrent()
            verify(exactly = 2) { http.newWebSocket(any(), any()) }
            advanceTimeBy(2002); runCurrent()
            verify(exactly = 3) { http.newWebSocket(any(), any()) }
        } finally { job.cancelAndJoin() }
    }
}
