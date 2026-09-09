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
        coEvery { getFreshToken() } returns "test-token"
        every { getServerUrl() } returns "http://127.0.0.1:12345"
    }
    private val socket = mockk<WebSocket>(relaxed = true) {
        every { send(any<String>()) } returns true
        every { queueSize() } returns 0L
    }
    private lateinit var listener: WebSocketListener
    private val http = mockk<OkHttpClient> {
        every { newWebSocket(any(), any()) } answers {
            listener = secondArg()
            socket
        }
    }
    private val client = SphereWebSocketClient(http, auth, Json)

    @Test fun cleanServerCloseWaitsBeforeReconnect() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        listener.onOpen(socket, mockk(relaxed = true))
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
        listener.onOpen(socket, mockk(relaxed = true))
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
        listener.onOpen(socket, mockk(relaxed = true))
        runCurrent()
        client.forceReconnectNow()
        verify(atLeast = 1) { socket.cancel() }
        job.cancelAndJoin()
    }

    @Test fun closingHandshakeIsAcknowledged() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        listener.onOpen(socket, mockk(relaxed = true))
        listener.onClosing(socket, 1000, "server_shutdown")
        verify { socket.close(1000, "server_shutdown") }
        job.cancelAndJoin()
    }

    @Test fun failureAfterOpenUsesBackoff() = runTest {
        val job = launch { client.connect("local-test-device") }
        runCurrent()
        listener.onOpen(socket, mockk(relaxed = true))
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
        listener.onOpen(socket, mockk(relaxed = true))
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
