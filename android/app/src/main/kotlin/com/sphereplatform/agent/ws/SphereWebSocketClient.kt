package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
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

/**
 * SphereWebSocketClient — надёжный WS-клиент с:
 * - Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s
 * - Smart circuit breaker: 10 NETWORK ошибок → 5 минут паузы
 *   AUTH ошибки (4001) НЕ считаются — вместо этого запрашивается новый токен
 * - First-message auth (JWT в первом сообщении после onOpen, не в URL)
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

    @Volatile
    var isConnected = false
        private set

    // Smart circuit breaker — only counts NETWORK failures, not auth
    private var consecutiveFailures = 0
    private val CIRCUIT_OPEN_THRESHOLD = 10
    private var circuitOpenUntil = 0L
    private val CIRCUIT_COOL_DOWN_MS = 5 * 60 * 1000L

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
        shouldStop = false
        this.deviceId = deviceId
        reconnectLoop()
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
                // Нормальное закрытие — сбрасываем backoff и продолжаем
                consecutiveFailures = 0
                attempt = 0
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

        val connected = CompletableDeferred<Unit>()
        val disconnected = CompletableDeferred<Unit>()
        var closeCode = 0
        var closeReason = ""

        val listener = object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                webSocket = ws
                // First-message auth — ДО любых других сообщений
                ws.send("""{"token":"$token"}""")
                isConnected = true
                connected.complete(Unit)
                onConnected?.invoke()
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val msg = json.parseToJsonElement(text).jsonObject
                    onJsonMessage?.invoke(msg)
                } catch (e: Exception) {
                    Timber.w("Invalid JSON message: ${e.message}")
                }
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                onBinaryMessage?.invoke(bytes.toByteArray())
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                isConnected = false
                webSocket = null
                if (!connected.isCompleted) connected.completeExceptionally(t)
                else if (!disconnected.isCompleted) disconnected.complete(Unit)
                onDisconnected?.invoke(-1, t.message ?: "failure")
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                isConnected = false
                webSocket = null
                closeCode = code
                closeReason = reason
                disconnected.complete(Unit)
                onDisconnected?.invoke(code, reason)
            }
        }

        httpClient.newWebSocket(request, listener)
        connected.await()     // Ждём успешного onOpen
        disconnected.await()  // Ждём закрытия или сбоя

        // After connection closed — check close code for auth/heartbeat rejection
        if (closeCode == CODE_INVALID_TOKEN || closeCode == CODE_AUTH_TIMEOUT
            || closeCode == CODE_HEARTBEAT_TIMEOUT || closeCode == CODE_DEVICE_NOT_FOUND
        ) {
            throw AuthRejectedException(closeCode, closeReason)
        }
    }

    private fun calculateBackoff(attempt: Int): Long =
        (1000L * (1L shl attempt.coerceAtMost(5))).coerceAtMost(30_000L)

    fun sendJson(message: JsonObject): Boolean {
        val ws = webSocket ?: return false
        return ws.send(message.toString())
    }

    fun sendBinary(data: ByteArray): Boolean {
        val ws = webSocket ?: return false
        return ws.send(data.toByteString())
    }

    /**
     * Форсированный immediate reconnect — вызывается при восстановлении сети.
     * Прерывает текущий backoff delay без ожидания его истечения.
     */
    fun forceReconnectNow() {
        reconnectTrigger.trySend(Unit)
    }

    fun disconnect() {
        shouldStop = true
        webSocket?.close(1000, "client_disconnect")
        webSocket = null
        isConnected = false
        reconnectTrigger.trySend(Unit)
    }
}

class AuthException(message: String) : Exception(message)
class AuthRejectedException(val code: Int, reason: String) : Exception("Auth rejected: code=$code reason=$reason")
