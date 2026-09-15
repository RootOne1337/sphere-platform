package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

/** Execute the production reconnect loop and listeners without network listeners. */
@OptIn(ExperimentalCoroutinesApi::class)
class WebSocketAuthenticationTest {
    private val deviceId = "d4b781b0-6571-4e94-9183-a7c36715e7e2"
    private val auth = mockk<AuthTokenStore>(relaxed = true) {
        every { getDeviceId() } returns "d4b781b0-6571-4e94-9183-a7c36715e7e2"
        coEvery { getFreshTokenForRoute(any(), any()) } returns "isolated-token"
        every { connectionRoutesSnapshot() } returns AuthTokenStore.ConnectionRoutes(0, listOf("https://isolated.invalid"))
        every { acceptConnectionRoute(any(), any()) } returns true
        every { getServerUrl() } returns "https://isolated.invalid"
    }
    private val socket = mockk<WebSocket>(relaxed = true) {
        every { send(any<String>()) } returns true
        every { send(any<okio.ByteString>()) } returns true
        every { queueSize() } returns 0L
    }
    private val listeners = mutableListOf<WebSocketListener>()
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
        every { newWebSocket(any(), any()) } answers { listeners.add(secondArg()); socket }
    }
    private val client = SphereWebSocketClient(http, auth, Json)
    private var connectedEvents = 0
    private var commandEvents = 0
    private var binaryEvents = 0

    init {
        client.onConnected = { connectedEvents++ }
        client.onJsonMessage = { commandEvents++ }
        client.onBinaryMessage = { binaryEvents++ }
    }

    private fun open() = listeners.last().onOpen(socket, mockk(relaxed = true))
    private fun ack(device: String = deviceId, version: String = "1") =
        """{"type":"auth_ok","device_id":"$device","protocol_version":$version}"""

    @Test fun transportOpenDoesNotAnnounceOrSendApplicationTraffic() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open(); runCurrent()
            assertFalse("Transport open is not server authentication", client.isConnected)
            assertEquals(0, connectedEvents)
            assertFalse(client.sendJson(buildJsonObject { put("type", "command_result") }))
            assertFalse(client.sendBinary(byteArrayOf(1)))
            verify(exactly = 1) { socket.send(any<String>()) } // auth frame only
        } finally { job.cancelAndJoin() }
    }

    @Test fun validAckAnnouncesOnceAndIsNotDispatchedAsACommand() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            repeat(2) { listeners.last().onMessage(socket, ack()) }
            runCurrent()
            assertTrue(client.isConnected)
            assertEquals(1, connectedEvents)
            assertEquals(0, commandEvents)
            listeners.last().onMessage(socket, """{"type":"ping","ts":1}""")
            listeners.last().onMessage(socket, byteArrayOf(1).toByteString())
            assertEquals(1, commandEvents)
            assertEquals(1, binaryEvents)
            assertTrue(client.sendJson(buildJsonObject { put("type", "pong") }))
        } finally { job.cancelAndJoin() }
    }

    @Test fun silentAuthAfterOpenTimesOutAndRetries() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open(); runCurrent()
            advanceTimeBy(22_001); runCurrent()
            assertTrue(job.isActive)
            assertEquals("Silent auth must not leave the channel apparently online", 2, listeners.size)
            assertFalse(client.isConnected)
            assertEquals(0, connectedEvents)
        } finally { job.cancelAndJoin() }
    }

    @Test fun authRejectionBeforeAckRefreshesImmediatelyWithoutHandshakeTimeout() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            listeners.last().onClosed(socket, 4001, "invalid_token")
            runCurrent()
            verify(exactly = 1) { auth.clearTokenCache() }
            advanceTimeBy(4_001); runCurrent()
            assertEquals(2, listeners.size)
        } finally { job.cancelAndJoin() }
    }

    @Test fun callbacksFromTimedOutHandshakeCannotRestoreConnectedState() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent()
            val expired = listeners.single()
            advanceTimeBy(20_000); runCurrent() // in backoff; next generation has not started
            expired.onOpen(socket, mockk(relaxed = true))
            expired.onMessage(socket, ack())
            expired.onMessage(socket, """{"type":"ping"}""")
            assertFalse(client.isConnected)
            assertEquals(0, connectedEvents)
            assertEquals(0, commandEvents)
        } finally { job.cancelAndJoin() }
    }

    @Test fun messagesFromFailedSessionAreIgnoredDuringBackoff() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            val failed = listeners.single()
            failed.onMessage(socket, ack()); runCurrent()
            failed.onFailure(socket, IOException("isolated network loss"), null); runCurrent()
            val before = commandEvents
            failed.onMessage(socket, """{"type":"execute_dag"}""")
            failed.onMessage(socket, byteArrayOf(1).toByteString())
            assertEquals(before, commandEvents)
            assertEquals(0, binaryEvents)
            assertFalse(client.isConnected)
        } finally { job.cancelAndJoin() }
    }

    private fun rejectsBeforeAuth(message: String) = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            listeners.single().onMessage(socket, message); runCurrent()
            assertFalse(client.isConnected)
            assertEquals(0, connectedEvents)
            assertEquals(0, commandEvents)
            advanceTimeBy(2_001); runCurrent()
            assertEquals(2, listeners.size)
            verify(exactly = 0) { auth.clearTokenCache() }
        } finally { job.cancelAndJoin() }
    }

    @Test fun wrongDeviceAckCannotEnableChannel() = rejectsBeforeAuth(ack(device = "another-device"))
    @Test fun unsupportedAckVersionCannotEnableChannel() = rejectsBeforeAuth(ack(version = "2"))
    @Test fun stringAckVersionCannotEnableChannel() = rejectsBeforeAuth(ack(version = "\"1\""))
    @Test fun malformedAckCannotEnableChannel() = rejectsBeforeAuth("{")
    @Test fun commandBeforeAckIsNotExecuted() = rejectsBeforeAuth("""{"type":"execute_dag"}""")

    @Test fun cancellationWhileAwaitingAckReleasesSocket() = runTest {
        val job = launch { client.connect() }
        runCurrent(); open()
        job.cancelAndJoin()
        listeners.single().onMessage(socket, ack())
        assertFalse(client.isConnected)
        verify(atLeast = 1) { socket.cancel() }
    }

    @Test fun rejectedAckCannotBeReplacedBeforeCleanupRuns() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            listeners.single().onMessage(socket, ack(device = "wrong-device"))
            listeners.single().onMessage(socket, ack()) // no coroutine scheduling between callbacks
            assertFalse(client.isConnected)
            assertEquals(0, connectedEvents)
        } finally { job.cancelAndJoin() }
    }

    @Test fun failedSocketCannotReauthenticateBeforeCleanupRuns() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            listeners.single().onMessage(socket, ack()); runCurrent()
            listeners.single().onFailure(socket, IOException("isolated failure"), null)
            open()
            listeners.single().onMessage(socket, ack())
            assertFalse(client.isConnected)
            assertEquals(1, connectedEvents)
            verify(exactly = 1) { socket.send(any<String>()) }
        } finally { job.cancelAndJoin() }
    }

    @Test fun binaryBeforeAckCannotReachApplication() = runTest {
        val job = launch { client.connect() }
        try {
            runCurrent(); open()
            listeners.single().onMessage(socket, byteArrayOf(1).toByteString()); runCurrent()
            assertFalse(client.isConnected)
            assertEquals(0, binaryEvents)
            assertEquals(0, connectedEvents)
            advanceTimeBy(2_001); runCurrent()
            assertEquals(2, listeners.size)
        } finally { job.cancelAndJoin() }
    }

    @Test fun transportCancellationCannotReenterAnAuthenticatedListener() = runTest {
        val job = launch { client.connect() }
        runCurrent(); open()
        listeners.single().onMessage(socket, ack()); runCurrent()
        every { socket.cancel() } answers {
            // Model an already queued reader callback running during transport teardown.
            listeners.single().onMessage(socket, """{"type":"execute_dag"}""")
        }
        job.cancelAndJoin()
        assertEquals("Invalidate the session before invoking transport teardown", 0, commandEvents)
        assertFalse(client.isConnected)
    }
}
