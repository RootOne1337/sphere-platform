package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.network.forManagementRoute
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
import javax.inject.Singleton
import java.util.concurrent.atomic.AtomicLong
import kotlin.random.Random

/**
 * SphereWebSocketClient — надёжный WS-клиент с:
 * - Exponential retry windows with equal jitter (first retry 1–2s, cap 15–30s)
 * - Smart circuit breaker: 10 consecutive transport failures → 60 seconds cooldown
 *   Short authenticated sessions count as failures; only 60 seconds of stable
 *   transport resets retry debt. Credential rejections refresh the token.
 *   Legacy backend used 4001 for session replacement too; that reason is not
 *   an auth rejection and must not invalidate a healthy device credential.
 * - First-message auth and target-bound server acknowledgement before application traffic
 * - Network change detection через [forceReconnectNow]
 * - Безопасная остановка через [disconnect]
 */
@Singleton
class SphereWebSocketClient(
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
    private val json: Json,
    private val ensureInstance: suspend () -> Unit = {},
) {
    private var webSocket: WebSocket? = null

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
        private const val CODE_NORMAL_CLOSURE = 1000
        private const val CODE_GOING_AWAY = 1001
        private const val STABLE_CONNECTION_WINDOW_MS = 60_000L
        private const val REASON_SESSION_REPLACED = "replaced_by_new_connection"

        private fun isAuthenticationRejection(code: Int, reason: String): Boolean =
            (code == CODE_INVALID_TOKEN && reason != REASON_SESSION_REPLACED) ||
                code == CODE_AUTH_TIMEOUT || code == CODE_DEVICE_NOT_FOUND

        private fun requiresTransportRetry(code: Int): Boolean =
            code != CODE_NORMAL_CLOSURE && code != CODE_GOING_AWAY
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
     * Используется [ConfigWatchdog] для проверки настроенного config endpoint —
     * возможно server_url сменился и нужно переподключиться на новый адрес.
     */
    var onCircuitBreakerOpen: (() -> Unit)? = null

    suspend fun connect() {
        if (!connectMutex.tryLock()) return
        try {
            shouldStop = false
            reconnectLoop()
        } finally {
            connectMutex.unlock()
        }
    }

    private suspend fun reconnectLoop() {
        var attempt = 0
        var failedRoute: String? = null
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

            var route: String? = null
            try {
                ensureInstance()
                val routes = authStore.connectionRoutesSnapshot()
                val previousIndex = routes.urls.indexOf(failedRoute)
                route = routes.urls.getOrNull(if (previousIndex >= 0) (previousIndex + 1) % routes.urls.size else 0)
                if (route == null) throw AuthException("No management route stored")
                connectOnce(routes, route) {
                    // An auth acknowledgement alone is not evidence of a healthy
                    // route. Retain retry debt until the transport survives a full
                    // stability window so rapid close/reopen loops reach failover
                    // and the circuit breaker instead of retrying forever at 1–2s.
                    consecutiveFailures = 0
                    circuitOpenUntil = 0L
                    attempt = 0
                    failedRoute = null
                }
                // A clean server restart still needs a paced retry. Resetting to
                // zero bypassed all delay and synchronized reconnecting devices.
                consecutiveFailures = 0
                attempt = 1
                failedRoute = null
            } catch (e: CancellationException) {
                throw e
            } catch (e: AuthRejectedException) {
                // Auth rejected by server — DON'T circuit break.
                // Clear token cache so next attempt gets a fresh token.
                Timber.w("Auth rejected (code=${e.code}), clearing token cache")
                authStore.clearTokenCache()
                failedRoute = route
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
                failedRoute = route
                consecutiveFailures++
                attempt++

                // При первом обрыве запрашиваем свежих кандидатов из config endpoint.
                // Перебор сохранённых маршрутов не ждёт доступности discovery.
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
    private suspend fun connectOnce(
        routes: AuthTokenStore.ConnectionRoutes,
        route: String,
        onAuthenticated: () -> Unit,
    ) {
        // Service may start before enrollment. Re-read the assigned UUID on every attempt.
        val expectedDeviceId = authStore.getDeviceId() ?: throw AuthException("No assigned device ID stored")
        val token = authStore.getFreshTokenForRoute(routes, route)
            ?: throw AuthException("No auth token stored")
        val wsUrl = "$route/ws/android/$expectedDeviceId"
        val request = Request.Builder().url(wsUrl).build()
        val attemptGeneration = synchronized(wsLock) { ++generation }

        val connected = CompletableDeferred<Unit>()
        val disconnected = CompletableDeferred<Unit>()
        val attemptStartedAtMs = monotonicTimeMs()
        val authenticatedAtMs = AtomicLong(0L)
        val routeSlot = routes.urls.indexOf(route)
        var closeCode = 0
        var closeReason = ""
        var stableSession: Boolean
        var authSent = false // guarded by wsLock

        fun logLifecycle(
            event: String,
            closeCode: Int? = null,
            reasonPresent: Boolean? = null,
            error: Throwable? = null,
            responseCode: Int? = null,
        ) {
            val now = monotonicTimeMs()
            val authenticatedAt = authenticatedAtMs.get()
            val fields = buildString {
                append("ws_lifecycle event=$event attempt_id=$attemptGeneration ")
                append("route_slot=$routeSlot route_count=${routes.urls.size} ")
                append("phase=${if (authenticatedAt > 0L) "authenticated" else "pre_auth"} ")
                append("elapsed_ms=${(now - attemptStartedAtMs).coerceAtLeast(0L)} ")
                if (authenticatedAt > 0L) {
                    append("authenticated_ms=${(now - authenticatedAt).coerceAtLeast(0L)} ")
                }
                if (closeCode != null) append("close_code=$closeCode ")
                if (reasonPresent != null) append("reason_present=$reasonPresent ")
                if (responseCode != null) append("response_code=$responseCode ")
                if (error != null) {
                    append("error_type=${error.javaClass.simpleName} ")
                    error.cause?.let { append("cause_type=${it.javaClass.simpleName} ") }
                }
            }.trimEnd()
            // Never include the route URL, device ID, token, close reason, or exception message.
            Timber.i(fields)
        }

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
                            if (authStore.getDeviceId() != expectedDeviceId || !authStore.acceptConnectionRoute(routes, route)) {
                                connected.completeExceptionally(IOException("Management route changed during authentication"))
                                return
                            }
                            isConnected = true
                            authenticatedAtMs.compareAndSet(0L, monotonicTimeMs())
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
                if (current) {
                    logLifecycle(
                        event = "onFailure",
                        error = t,
                        responseCode = response?.code,
                    )
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
                if (current) {
                    logLifecycle(
                        event = "onClosed",
                        closeCode = code,
                        reasonPresent = reason.isNotBlank(),
                    )
                }
                if (!connected.isCompleted) {
                    val failure = if (isAuthenticationRejection(code, reason)) AuthRejectedException(code, reason)
                    else IOException("WebSocket closed before authentication acknowledgement: $code")
                    connected.completeExceptionally(failure)
                }
                disconnected.complete(Unit)
                if (current) onDisconnected?.invoke(code, reason)
            }
        }

        val socket = httpClient.forManagementRoute(route).newWebSocket(request, listener)
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
                logLifecycle(event = "handshake_timeout", error = e)
                throw IOException("WebSocket authentication handshake timeout", e)
            }
            stableSession = withTimeoutOrNull(STABLE_CONNECTION_WINDOW_MS) {
                disconnected.await()
                false
            } ?: true
            if (stableSession) onAuthenticated()
            if (!disconnected.isCompleted) disconnected.await()
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

        // Auth rejection refreshes credentials. Heartbeat timeout (4008), missing
        // close status (1005), and other non-graceful closes are transport failures:
        // retain auth and use the existing jitter/failover/circuit-breaker path.
        if (isAuthenticationRejection(closeCode, closeReason)) {
            throw AuthRejectedException(closeCode, closeReason)
        }
        if (!stableSession || requiresTransportRetry(closeCode)) {
            throw IOException("WebSocket closed before a stable session: code=$closeCode")
        }
    }

    private fun calculateBackoff(attempt: Int): Long {
        val ceiling = (1000L * (1L shl attempt.coerceIn(0, 5))).coerceAtMost(30_000L)
        // Independent retry times spread fleet recovery; a positive lower bound
        // prevents busy retries even when the server repeatedly closes cleanly.
        return Random.nextLong(ceiling / 2, ceiling + 1)
    }

    private fun monotonicTimeMs(): Long = System.nanoTime() / 1_000_000L

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
    fun forceReconnectNow(bypassDebounce: Boolean = false) {
        // FIX AUDIT-1.2: Debounce — защита от reconnect flood при мигании Wi-Fi
        val now = System.currentTimeMillis()
        if (!bypassDebounce && now - lastForceReconnectAt < FORCE_RECONNECT_DEBOUNCE_MS) {
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
