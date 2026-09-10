package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.Json
import okhttp3.*
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class WebSocketLifecycleTest {
    private val auth = mockk<AuthTokenStore>(relaxed = true) {
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
        val job = launch { client.connect("local-test-device") }
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
        val job = launch { client.connect("local-test-device") }
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
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        job.cancelAndJoin()
        verify(atLeast = 1) { socket.cancel() }
        assertFalse(client.isConnected)
    }

    @Test fun forcedReconnectClosesActiveTransport() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        authenticateSocket()
        runCurrent()
        client.forceReconnectNow()
        verify(atLeast = 1) { socket.cancel() }
        job.cancelAndJoin()
    }

    @Test fun closingHandshakeIsAcknowledged() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        authenticateSocket()
        listener.onClosing(socket, 1000, "server_shutdown")
        verify { socket.close(1000, "server_shutdown") }
        job.cancelAndJoin()
    }

    @Test fun failureAfterOpenUsesBackoff() = runTest {
        val job = launch { client.connect("local-test-device") }
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

    @Test fun videoBackpressureDoesNotFillOkHttpQueue() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        authenticateSocket()
        every { socket.queueSize() } returns 2L * 1024 * 1024
        assertFalse(client.sendBinary(ByteArray(1024)))
        verify(exactly = 0) { socket.send(any<okio.ByteString>()) }
        job.cancelAndJoin()
    }

    @Test fun handshakeTimeoutRetriesInsteadOfCancellingConnectLoop() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        advanceTimeBy(22_001)
        runCurrent()
        assertTrue(job.isActive)
        verify(atLeast = 1) { socket.cancel() }
        verify(exactly = 2) { http.newWebSocket(any(), any()) }
        job.cancelAndJoin()
    }
}
