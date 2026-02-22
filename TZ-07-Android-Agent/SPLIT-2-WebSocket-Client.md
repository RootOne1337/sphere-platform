# SPLIT-2 — WebSocket Client (Reconnect + Circuit Breaker)

**ТЗ-родитель:** TZ-07-Android-Agent  
**Ветка:** `stage/7-android`  
**Задача:** `SPHERE-037`  
**Исполнитель:** Android  
**Оценка:** 1 день  
**Блокирует:** TZ-07 SPLIT-3 (Command Handler)

---

## Цель Сплита

Надёжный WebSocket клиент с exponential backoff, circuit breaker при 10 неудачных попытках, first-message auth, обработка network changes.

---

## Шаг 1 — SphereWebSocketClient

```kotlin
// AndroidAgent/network/SphereWebSocketClient.kt
@Singleton
class SphereWebSocketClient @Inject constructor(
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
    private val json: Json,
) {
    // Состояние
    private var webSocket: WebSocket? = null
    private var deviceId: String = ""
    
    @Volatile var isConnected = false
        private set
    
    // Circuit breaker
    private var consecutiveFailures = 0
    private val CIRCUIT_OPEN_THRESHOLD = 10
    private var circuitOpenUntil = 0L
    private val CIRCUIT_COOL_DOWN_MS = 5 * 60 * 1000L  // 5 минут
    
    // Callbacks — устанавливаются CommandHandler'ом
    var onJsonMessage: ((JsonObject) -> Unit)? = null
    var onBinaryMessage: ((ByteArray) -> Unit)? = null
    var onConnected: (() -> Unit)? = null
    var onDisconnected: ((code: Int, reason: String) -> Unit)? = null
    
    suspend fun connect(deviceId: String) {
        this.deviceId = deviceId
        reconnectLoop()
    }
    
    private suspend fun reconnectLoop() {
        var attempt = 0
        
        while (true) {
            // Circuit breaker check
            if (System.currentTimeMillis() < circuitOpenUntil) {
                val waitMs = circuitOpenUntil - System.currentTimeMillis()
                Timber.w("Circuit open, waiting ${waitMs/1000}s before next attempt")
                delay(waitMs)
                consecutiveFailures = 0
            }
            
            val backoffMs = calculateBackoff(attempt)
            if (attempt > 0) {
                Timber.d("Reconnect attempt $attempt, backoff ${backoffMs}ms")
                delay(backoffMs)
            }
            
            try {
                connectOnce()
                // Успешное подключение
                consecutiveFailures = 0
                attempt = 0
                
                // Ждать отключения
                suspendUntilDisconnected()
                
            } catch (e: CancellationException) {
                throw e  // Не перехватываем
            } catch (e: Exception) {
                Timber.w(e, "WS connect failed")
                consecutiveFailures++
                attempt++
                
                if (consecutiveFailures >= CIRCUIT_OPEN_THRESHOLD) {
                    circuitOpenUntil = System.currentTimeMillis() + CIRCUIT_COOL_DOWN_MS
                    Timber.e("Circuit breaker OPEN after $consecutiveFailures failures")
                }
            }
        }
    }
    
    private suspend fun connectOnce() {
        // КРИТИЧНО: JWT access_token живёт 15 минут.
        // Агент работает 24/7 — мы обновляем токен ПЕРЕД подключением,
        // чтобы first-message содержал валидный токен.
        val token = authStore.getFreshToken()  // возвращает свежий access token
            ?: throw AuthException("No auth token stored")
        
        val wsUrl = "${authStore.getServerUrl()}/ws/android/$deviceId"
        val request = Request.Builder().url(wsUrl).build()
        
        val connected = CompletableDeferred<Unit>()
        val disconnected = CompletableDeferred<Unit>()
        
        val wsListener = object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                webSocket = ws
                // First-message auth — ДО любых других сообщений
                ws.send(json.encodeToString(mapOf("token" to token)))
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
                if (!connected.isCompleted) {
                    connected.completeExceptionally(t)
                } else {
                    disconnected.complete(Unit)
                }
                onDisconnected?.invoke(-1, t.message ?: "failure")
            }
            
            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                isConnected = false
                webSocket = null
                disconnected.complete(Unit)
                onDisconnected?.invoke(code, reason)
            }
        }
        
        httpClient.newWebSocket(request, wsListener)
        connected.await()  // Ждём успешного onOpen
        disconnected.await()  // Ждём закрытия
    }
    
    private fun calculateBackoff(attempt: Int): Long {
        // Exponential: 1s, 2s, 4s, 8s, 16s, 30s (max)
        return (1000L * (1L shl attempt.coerceAtMost(5))).coerceAtMost(30_000L)
    }
    
    fun sendJson(message: JsonObject): Boolean {
        val ws = webSocket ?: return false
        return ws.send(json.encodeToString(message))
    }
    
    fun sendBinary(data: ByteArray): Boolean {
        val ws = webSocket ?: return false
        return ws.send(ByteString.of(*data))
    }
    
    fun disconnect() {
        webSocket?.close(1000, "client_disconnect")
        webSocket = null
        isConnected = false
    }
    
    private suspend fun suspendUntilDisconnected() {
        // Реализация через CompletableDeferred внутри connectOnce
    }
}
```

---

## Шаг 3 — AuthTokenStore: автоматический refresh JWT

```kotlin
// AndroidAgent/auth/AuthTokenStore.kt
@Singleton
class AuthTokenStore @Inject constructor(
    private val prefs: EncryptedSharedPrefs,   // хранится в Keystore-зашифрованном SharedPreferences
    private val httpClient: OkHttpClient,
) {
    private val serverUrl: String get() = prefs.getString("server_url") ?: ""
    private val tokenMutex = Mutex()

    fun getServerUrl(): String = serverUrl

    /**
     * Возвращает access_token, предварительно обновляя его если осталось < 5 мин.
     * Проактивная проверка обеспечивает что first-message WS всегда содержит неистёкший токен.
     */
    suspend fun getFreshToken(): String? = tokenMutex.withLock {
        val accessToken = prefs.getString("access_token") ?: return@withLock null
        val expiresAt   = prefs.getLong("access_token_expires_at", 0L)
        val refreshToken = prefs.getString("refresh_token") ?: return@withLock accessToken

        //  Если tokens заканчивается через 5 мин — обновить
        if (System.currentTimeMillis() + 5 * 60_000L < expiresAt) {
            return@withLock accessToken   // ещё валиден
        }

        return@withLock try {
            refreshTokenRequest(refreshToken)
        } catch (e: Exception) {
            Timber.w(e, "Token refresh failed, using existing token")
            accessToken  // попытка с истекшим — всё равно, reconnect обработает в цикле
        }
    }

    private suspend fun refreshTokenRequest(refreshToken: String): String {
        // Используем тот же OkHttpClient (suspend через coroutine)
        val request = Request.Builder()
            .url("$serverUrl/api/v1/auth/refresh")
            .addHeader("Cookie", "refresh_token=$refreshToken")
            .post(RequestBody.create(null, ByteArray(0)))
            .build()
        val response = httpClient.newCall(request).await()  // расширение okhttp-coroutines
        if (!response.isSuccessful) throw IOException("Refresh failed: ${response.code}")
        val body = response.body?.string() ?: throw IOException("Empty refresh response")
        val json = Json.parseToJsonElement(body).jsonObject
        val newAccessToken = json["access_token"]!!.jsonPrimitive.content
        val expiresIn      = json["expires_in"]?.jsonPrimitive?.long ?: 900L
        prefs.putString("access_token", newAccessToken)
        prefs.putLong("access_token_expires_at", System.currentTimeMillis() + expiresIn * 1000)
        // Rotate refresh token если пришёл новый
        json["refresh_token"]?.jsonPrimitive?.content?.let {
            prefs.putString("refresh_token", it)
        }
        Timber.d("Access token refreshed, expires in ${expiresIn}s")
        return newAccessToken
    }

    fun saveTokens(accessToken: String, refreshToken: String, expiresIn: Long) {
        prefs.putString("access_token", accessToken)
        prefs.putString("refresh_token", refreshToken)
        prefs.putLong("access_token_expires_at", System.currentTimeMillis() + expiresIn * 1000)
    }
}
```

> **Почему не периодическая фоновая задача обновления:**
> Reconnect и так вызывается каждые ~30s (heartbeat) или при обрыве WS. Токен обновляется
> проактивно в `getFreshToken()` перед каждым reconnect — без лишных background coroutine.

```kotlin
// AndroidAgent/network/NetworkChangeHandler.kt
@Singleton
class NetworkChangeHandler @Inject constructor(
    @ApplicationContext private val context: Context,
    private val wsClient: SphereWebSocketClient,
) {
    fun register() {
        val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        
        connectivityManager.registerNetworkCallback(request, object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Timber.i("Сеть доступна, форсируем reconnect")
                // FIX ARCH-7: БЫЛО — пустой блок, агент ждал backoff до 30с
                // СТАЛО — прерываем текущий delay и reconnect немедленно
                if (!wsClient.isConnected) {
                    wsClient.forceReconnectNow()
                }
            }
            
            override fun onLost(network: Network) {
                Timber.w("Сеть потеряна")
                // WebSocket получит onFailure автоматически
            }
        })
    }
}
```

---

## Критерии готовности

- [ ] `getFreshToken()` проверяет expiry и обновляет токен, если осталось < 5 мин
- [ ] First-message auth: token в первом сообщении, не в URL
- [ ] Backoff: 1s → 2s → 4s → 8s → 16s → 30s (не растёт выше 30)
- [ ] 10 последовательных ошибок → circuit open 5 минут
- [ ] Circuit breaker сбрасывается при успешном подключении
- [ ] Network change detection: reconnect запускается при восстановлении сети
- [ ] `sendBinary()` возвращает false если WS закрыт (не крашится)
- [ ] Агент работает 24/7 без отвалов — JWT обновляется автоматически при каждом reconnect
