package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import java.io.IOException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.random.Random

/**
 * SphereWebSocketClient — надёжный WS-клиент с:
 * - Exponential retry windows with equal jitter (first retry 1–2s, cap 15–30s)
 * - Smart circuit breaker: 10 NETWORK ошибок → 60 секунд паузы
 *   AUTH ошибки (4001) НЕ считаются — вместо этого запрашивается новый токен
 * - First-message auth and target-bound server acknowledgement before application traffic
 * - Network change detection через [forceReconnectNow]
 * - Безопасная остановка через [disconnect]
 */
@Singleton
class SphereWebSocketClient @Inject constructor(
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
    private val json: Json,
) {
    private var webSocket: WebSocket? = null
    private var deviceId: String = ""

    // FIX AUDIT-1.7: Lock для атомарного обновления webSocket + isConnected
    private val wsLock = Any()
    private val connectMutex = Mutex()
    private var generation = 0L

    @Volatile
    var isConnected = false
        private set

    // Smart circuit breaker — only counts NETWORK failures, not auth
    private var consecutiveFailures = 0
    private val CIRCUIT_OPEN_THRESHOLD = 10
    private var circuitOpenUntil = 0L
    // FIX-RECONNECT: 60s вместо 5 мин — при смене tunnel URL агент не должен ждать долго
    private val CIRCUIT_COOL_DOWN_MS = 60 * 1000L

    // FIX AUDIT-1.2: Debounce для forceReconnectNow — защита от reconnect flood
    // при мигании Wi-Fi на слабом эмуляторе
    @Volatile
    private var lastForceReconnectAt = 0L
    private val FORCE_RECONNECT_DEBOUNCE_MS = 5_000L

    // Server close codes that indicate auth/permission problems (don't circuit break)
    companion object {
        private const val CODE_INVALID_TOKEN = 4001
        private const val CODE_AUTH_TIMEOUT = 4003
        private const val CODE_DEVICE_NOT_FOUND = 4004
        private const val CODE_HEARTBEAT_TIMEOUT = 4008
    }

    // Управление reconnect loop
    @Volatile
    private var shouldStop = false
    private val reconnectTrigger = Channel<Unit>(Channel.CONFLATED)

    // Callbacks — устанавливаются CommandDispatcher'ом
    var onJsonMessage: ((JsonObject) -> Unit)? = null
    var onBinaryMessage: ((ByteArray) -> Unit)? = null
    var onConnected: (() -> Unit)? = null
    var onDisconnected: ((code: Int, reason: String) -> Unit)? = null

    /**
     * Вызывается при открытии circuit breaker (после N последовательных ошибок).
     * Используется [ConfigWatchdog] для немедленной проверки конфига из Git —
     * возможно server_url сменился и нужно переподключиться на новый адрес.
     */
    var onCircuitBreakerOpen: (() -> Unit)? = null

    suspend fun connect(deviceId: String) {
        if (!connectMutex.tryLock()) return
        try {
            shouldStop = false
            this.deviceId = deviceId
            reconnectLoop()
        } finally {
            connectMutex.unlock()
        }
    }

    private suspend fun reconnectLoop() {
        var attempt = 0
        while (!shouldStop) {
            // Circuit breaker check
            val now = System.currentTimeMillis()
            if (now < circuitOpenUntil) {
                val waitMs = circuitOpenUntil - now
                Timber.w("Circuit OPEN: waiting ${waitMs / 1000}s before retry")
                withTimeoutOrNull(waitMs) { reconnectTrigger.receive() }
                if (shouldStop) return
                consecutiveFailures = 0
            }

            if (attempt > 0) {
                val backoffMs = calculateBackoff(attempt)
                Timber.d("Reconnect attempt=$attempt, backoff=${backoffMs}ms")
                withTimeoutOrNull(backoffMs) { reconnectTrigger.receive() }
                if (shouldStop) return
            }

            try {
                connectOnce()
                // A clean server restart still needs a paced retry. Resetting to
                // zero bypassed all delay and synchronized reconnecting devices.
                consecutiveFailures = 0
                attempt = 1
            } catch (e: CancellationException) {
                throw e
            } catch (e: AuthRejectedException) {
                // Auth rejected by server — DON'T circuit break.
                // Clear token cache so next attempt gets a fresh token.
                Timber.w("Auth rejected (code=${e.code}), clearing token cache")
                authStore.clearTokenCache()
                attempt++
                // Short delay before retry with fresh token
                withTimeoutOrNull(2000L) { reconnectTrigger.receive() }
            } catch (e: AuthException) {
                // No token available locally — DON'T circuit break
                Timber.w(e, "No auth token — waiting for enrollment")
                attempt++
                withTimeoutOrNull(10_000L) { reconnectTrigger.receive() }
            } catch (e: Exception) {
                // Network/unknown failure — circuit breaker applies
                Timber.w(e, "WS connect failed (attempt=$attempt)")
                consecutiveFailures++
                attempt++

                // При первом обрыве — немедленно чекаем конфиг из Git
                // (server_url мог смениться → агент должен переподключиться мгновенно)
                if (consecutiveFailures == 1) {
                    Timber.i("Первый обрыв связи — запрашиваем проверку конфига")
                    onCircuitBreakerOpen?.invoke()
                }

                if (consecutiveFailures >= CIRCUIT_OPEN_THRESHOLD) {
                    circuitOpenUntil = System.currentTimeMillis() + CIRCUIT_COOL_DOWN_MS
                    consecutiveFailures = 0
                    Timber.e("Circuit OPEN after $CIRCUIT_OPEN_THRESHOLD failures, cool-down ${CIRCUIT_COOL_DOWN_MS / 1000}s")
                    // Повторный чек конфига при полном размыкании circuit breaker
                    onCircuitBreakerOpen?.invoke()
                }
            }
        }
    }

    /**
     * Открывает одно WS-соединение и блокируется до его закрытия.
     *
     * First-message auth: JWT отправляется первым сообщением в [onOpen],
     * НЕ в URL (токен в query-param виден в логах сервера и прокси).
     */
    private suspend fun connectOnce() {
        val token = authStore.getFreshToken()
            ?: throw AuthException("No auth token stored")
        val wsUrl = "${authStore.getServerUrl().trimEnd('/')}/ws/android/$deviceId"
        val request = Request.Builder().url(wsUrl).build()
        val attemptGeneration = synchronized(wsLock) { ++generation }

        val connected = CompletableDeferred<Unit>()
        val disconnected = CompletableDeferred<Unit>()
        var closeCode = 0
        var closeReason = ""
        var authSent = false // guarded by wsLock
        val expectedDeviceId = deviceId

        val listener = object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                // FIX AUDIT-1.7: Атомарное обновление webSocket + isConnected
                synchronized(wsLock) {
                    if (attemptGeneration != generation || shouldStop || connected.isCompleted || disconnected.isCompleted) {
                        ws.cancel()
                        return
                    }
                    webSocket = ws
                    // First-message auth — ДО любых других сообщений
                    if (!ws.send("""{"token":"$token"}""")) {
                        connected.completeExceptionally(IOException("Cannot send authentication"))
                        return
                    }
                    authSent = true
                }
            }

            override fun onMessage(ws: WebSocket, text: String) {
                if (synchronized(wsLock) { attemptGeneration != generation || shouldStop }) return
                try {
                    val msg = json.parseToJsonElement(text).jsonObject
                    val type = msg["type"]?.jsonPrimitive?.contentOrNull
                    val authenticatedNow = synchronized(wsLock) {
                        if (attemptGeneration != generation || shouldStop) return
                        if (!isConnected) {
                            // A failure/close is terminal even before the reconnect
                            // coroutine gets CPU time to invalidate this generation.
                            if (connected.isCompleted) return
                            val version = msg["protocol_version"]?.jsonPrimitive
                            if (!authSent || type != "auth_ok" ||
                                msg["device_id"]?.jsonPrimitive?.contentOrNull != expectedDeviceId ||
                                version?.isString != false || version.intOrNull != 1
                            ) {
                                connected.completeExceptionally(IOException("Invalid server authentication acknowledgement"))
                                return
                            }
                            isConnected = true
                            connected.complete(Unit)
                            true
                        } else {
                            false
                        }
                    }
                    if (authenticatedNow) {
                        onConnected?.invoke()
                        return
                    }
                    // Duplicate acknowledgements never replay the result journal twice.
                    if (type == "auth_ok") return
                    onJsonMessage?.invoke(msg)
                } catch (e: Exception) {
                    if (!connected.isCompleted) {
                        connected.completeExceptionally(IOException("Invalid server authentication acknowledgement", e))
                    }
                    Timber.w("Invalid WebSocket JSON message")
                }
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                synchronized(wsLock) {
                    if (attemptGeneration != generation || shouldStop) return
                    if (!isConnected) {
                        connected.completeExceptionally(IOException("Binary message before authentication acknowledgement"))
                        return
                    }
                }
                onBinaryMessage?.invoke(bytes.toByteArray())
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                val current = synchronized(wsLock) {
                    (attemptGeneration == generation).also {
                        if (it) {
                            isConnected = false
                            webSocket = null
                        }
                    }
                }
                if (!connected.isCompleted) connected.completeExceptionally(t)
                else if (!disconnected.isCompleted) disconnected.completeExceptionally(t)
                if (current) onDisconnected?.invoke(-1, t.message ?: "failure")
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                ws.close(code, reason)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                val current = synchronized(wsLock) {
                    (attemptGeneration == generation).also {
                        if (it) {
                            isConnected = false
                            webSocket = null
                        }
                    }
                }
                closeCode = code
                closeReason = reason
                if (!connected.isCompleted) {
                    val failure = if (code == CODE_INVALID_TOKEN || code == CODE_AUTH_TIMEOUT ||
                        code == CODE_DEVICE_NOT_FOUND || code == CODE_HEARTBEAT_TIMEOUT
                    ) AuthRejectedException(code, reason)
                    else IOException("WebSocket closed before authentication acknowledgement: $code")
                    connected.completeExceptionally(failure)
                }
                disconnected.complete(Unit)
                if (current) onDisconnected?.invoke(code, reason)
            }
        }

        val socket = httpClient.newWebSocket(request, listener)
        synchronized(wsLock) {
            if (attemptGeneration == generation && !shouldStop && !disconnected.isCompleted) {
                webSocket = socket
            } else {
                socket.cancel()
            }
        }
        try {
            try {
                withTimeout(20_000L) { connected.await() }
            } catch (e: TimeoutCancellationException) {
                currentCoroutineContext().ensureActive()
                throw IOException("WebSocket authentication handshake timeout", e)
            }
            disconnected.await()
        } finally {
            synchronized(wsLock) {
                if (attemptGeneration == generation) {
                    // Invalidate callbacks immediately, including the backoff window
                    // before the next attempt allocates its own generation.
                    ++generation
                    webSocket = null
                    isConnected = false
                }
            }
            // Transport cancellation can race with an already queued reader callback.
            // Make that callback stale before invoking external teardown code.
            socket.cancel()
        }

        // After connection closed — check close code for auth/heartbeat rejection
        if (closeCode == CODE_INVALID_TOKEN || closeCode == CODE_AUTH_TIMEOUT
            || closeCode == CODE_HEARTBEAT_TIMEOUT || closeCode == CODE_DEVICE_NOT_FOUND
        ) {
            throw AuthRejectedException(closeCode, closeReason)
        }
    }

    private fun calculateBackoff(attempt: Int): Long {
        val ceiling = (1000L * (1L shl attempt.coerceIn(0, 5))).coerceAtMost(30_000L)
        // Independent retry times spread fleet recovery; a positive lower bound
        // prevents busy retries even when the server repeatedly closes cleanly.
        return Random.nextLong(ceiling / 2, ceiling + 1)
    }

    fun sendJson(message: JsonObject): Boolean {
        if (!isConnected) return false
        val ws = synchronized(wsLock) { webSocket } ?: return false
        return ws.send(message.toString())
    }

    fun sendBinary(data: ByteArray): Boolean {
        if (!isConnected) return false
        val ws = synchronized(wsLock) { webSocket } ?: return false
        // Keep video from filling OkHttp's 16 MiB queue and closing the socket.
        // Return false to the existing adaptive bitrate controller before copying.
        if (ws.queueSize() + data.size > 1024 * 1024) return false
        return ws.send(data.toByteString())
    }

    /**
     * Форсированный immediate reconnect — вызывается при восстановлении сети
     * или при обнаружении нового server_url из ConfigWatchdog.
     * Прерывает текущий backoff delay и сбрасывает circuit breaker.
     */
    fun forceReconnectNow() {
        // FIX AUDIT-1.2: Debounce — защита от reconnect flood при мигании Wi-Fi
        val now = System.currentTimeMillis()
        if (now - lastForceReconnectAt < FORCE_RECONNECT_DEBOUNCE_MS) {
            Timber.d("forceReconnectNow: debounced (last ${now - lastForceReconnectAt}ms ago)")
            return
        }
        lastForceReconnectAt = now

        // Сбрасываем circuit breaker — вызывающий код (ConfigWatchdog/Network)
        // подтвердил что переподключение имеет смысл
        circuitOpenUntil = 0L
        consecutiveFailures = 0
        synchronized(wsLock) { webSocket }?.cancel()
        reconnectTrigger.trySend(Unit)
    }

    fun disconnect() {
        shouldStop = true
        synchronized(wsLock) {
            webSocket?.cancel()
            webSocket = null
            isConnected = false
        }
        reconnectTrigger.trySend(Unit)
    }
}

class AuthException(message: String) : Exception(message)
class AuthRejectedException(val code: Int, reason: String) : Exception("Auth rejected: code=$code reason=$reason")
