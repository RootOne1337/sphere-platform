package com.sphereplatform.agent.store

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.network.forManagementRoute
import com.sphereplatform.agent.network.normalizeManagementUrl
import dagger.Lazy
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import timber.log.Timber
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.CoroutineContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * AuthTokenStore — безопасное хранение JWT токена агента.
 *
 * Использует EncryptedSharedPreferences (AES256-GCM / AES256-SIV).
 * Ключи и значения никогда не хранятся в plaintext.
 *
 * [getFreshToken] проактивно обновляет access token если осталось < 5 мин до истечения.
 * При ошибке сохраняет текущее credential state; сервер отдельно проверяет expiry.
 */
@Singleton
class AuthTokenStore @Inject constructor(
    private val prefs: EncryptedSharedPreferences,
    private val lazyHttpClient: Lazy<OkHttpClient>,
) {
    companion object {
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_REFRESH_TOKEN = "refresh_token"
        private const val KEY_REFRESH_ROTATION_ID = "refresh_rotation_id"
        private const val KEY_ACCESS_TOKEN_EXPIRES_AT = "access_token_expires_at"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_PRIMARY_SERVER_URL = "primary_server_url"
        private const val KEY_FALLBACK_SERVER_URL = "fallback_server_url"
        private const val KEY_DEVICE_ID = "device_id"

        private const val REFRESH_THRESHOLD_MS = 5 * 60 * 1000L  // 5 минут
        private const val REFRESH_TIMEOUT_MS = 10_000L
        /** FIX E2: Лимит на размер response body при token refresh — защита от OOM. */
        private const val MAX_RESPONSE_CHARS = 64 * 1024
        /** Регулярка UUID — строгая проверка формата device_id. */
        private val UUID_REGEX = Regex(
            "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
    }

    private val tokenMutex = Mutex()
    /** Serializes background boot/periodic enrollment for this application store. */
    internal val enrollmentMutex = Mutex()
    private var serverUrlRevision = 0L
    private var credentialRevision = 0L

    internal data class RegistrationVersion(val credentials: Long, val routes: Long)

    /** UI and workers must preserve issuance order, including refresh rotation. */
    internal suspend fun <T> withRegistration(block: suspend () -> T): T = tokenMutex.withLock { block() }

    @Synchronized
    internal fun registrationVersion() = RegistrationVersion(credentialRevision, serverUrlRevision)

    /** Success means one complete preference edit has reached commit(true). */
    @Synchronized
    internal fun saveRegistration(
        expected: RegistrationVersion,
        deviceId: String,
        accessToken: String,
        refreshToken: String,
        expiresIn: Long,
        primaryUrl: String,
        fallbackUrl: String?,
        context: CoroutineContext,
    ) {
        context.ensureActive()
        if (expected != registrationVersion()) throw IOException("Registration state changed")
        if (!UUID_REGEX.matches(deviceId) || accessToken.isBlank() || refreshToken.isBlank() || expiresIn <= 0) {
            throw IOException("Invalid registration identity or credentials")
        }
        val expiresAt = try {
            Math.addExact(System.currentTimeMillis(), Math.multiplyExact(expiresIn, 1000L))
        } catch (e: ArithmeticException) {
            throw IOException("Invalid registration expiry", e)
        }
        val primary = normalizeManagementUrl(primaryUrl)
        val fallback = fallbackUrl?.let(::normalizeManagementUrl)?.takeIf { it != primary }
        val keys = listOf(KEY_SERVER_URL, KEY_PRIMARY_SERVER_URL, KEY_FALLBACK_SERVER_URL,
            KEY_DEVICE_ID, KEY_ACCESS_TOKEN, KEY_REFRESH_TOKEN, KEY_REFRESH_ROTATION_ID)
        val previous = keys.associateWith { prefs.getString(it, null) }
        val previousExpiry = if (prefs.contains(KEY_ACCESS_TOKEN_EXPIRES_AT)) {
            prefs.getLong(KEY_ACCESS_TOKEN_EXPIRES_AT, 0L)
        } else null
        try {
            val committed = prefs.edit()
                .putString(KEY_SERVER_URL, primary).putString(KEY_PRIMARY_SERVER_URL, primary)
                .putString(KEY_FALLBACK_SERVER_URL, fallback).putString(KEY_DEVICE_ID, deviceId)
                .putString(KEY_ACCESS_TOKEN, accessToken).putString(KEY_REFRESH_TOKEN, refreshToken)
                .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, expiresAt).remove(KEY_REFRESH_ROTATION_ID)
                .commit()
            if (!committed) throw IOException("Cannot persist registration")
        } catch (e: Exception) {
            // Failed commit may have changed memory. Readers use the same monitor,
            // so they cannot observe this candidate before rollback. Disk failure is
            // not a server rollback: issued credentials may still require recovery.
            try {
                prefs.edit().also { editor ->
                    previous.forEach { (key, value) -> editor.putString(key, value) }
                    if (previousExpiry == null) editor.remove(KEY_ACCESS_TOKEN_EXPIRES_AT)
                    else editor.putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, previousExpiry)
                }.apply()
            } catch (rollbackFailure: Exception) {
                e.addSuppressed(rollbackFailure)
            }
            throw IOException("Cannot persist registration", e)
        } finally {
            ++credentialRevision
            ++serverUrlRevision
        }
    }

    internal data class ServerUrlSnapshot(val url: String, val revision: Long)
    internal data class ConnectionRoutes(val revision: Long, val urls: List<String>)

    @Synchronized
    internal fun serverUrlSnapshot() = ServerUrlSnapshot(getServerUrl(), serverUrlRevision)

    @Synchronized
    internal fun replaceDiscoveredRoutes(expected: ServerUrlSnapshot, url: String, fallback: String?): Boolean {
        if (serverUrlRevision != expected.revision || getServerUrl() != expected.url) return false
        val primary = normalizeManagementUrl(url)
        val backup = (fallback ?: prefs.getString(KEY_FALLBACK_SERVER_URL, null))
            ?.let(::normalizeManagementUrl)?.takeIf { it != primary }
        val currentPrimary = prefs.getString(KEY_PRIMARY_SERVER_URL, null) ?: getServerUrl()
        if (primary == currentPrimary && backup == prefs.getString(KEY_FALLBACK_SERVER_URL, null)) return false
        commitRoutes(getServerUrl(), primary, backup)
        return true
    }

    @Synchronized
    internal fun connectionRoutesSnapshot(): ConnectionRoutes {
        val urls = listOf(getServerUrl(), prefs.getString(KEY_PRIMARY_SERVER_URL, null),
            prefs.getString(KEY_FALLBACK_SERVER_URL, null))
            .mapNotNull { value -> value?.let { runCatching { normalizeManagementUrl(it) }.getOrNull() } }
            .distinct()
        return ConnectionRoutes(serverUrlRevision, urls)
    }

    /** Only target-bound auth_ok can promote a discovered/backup connection route. */
    @Synchronized
    internal fun acceptConnectionRoute(expected: ConnectionRoutes, url: String): Boolean {
        if (serverUrlRevision != expected.revision || url !in expected.urls) return false
        if (getServerUrl() != url) {
            prefs.edit().putString(KEY_SERVER_URL, url).apply()
            ++serverUrlRevision
        }
        return true
    }

    /** Explicit provisioning replaces the previous installation's route pair. */
    @Synchronized
    fun saveServerRoutes(primaryUrl: String, fallbackUrl: String? = null) {
        val primary = normalizeManagementUrl(primaryUrl)
        val fallback = fallbackUrl?.let(::normalizeManagementUrl)?.takeIf { it != primary }
        commitRoutes(primary, primary, fallback)
    }

    private fun commitRoutes(active: String, primary: String, fallback: String?) {
        val keys = listOf(KEY_SERVER_URL, KEY_PRIMARY_SERVER_URL, KEY_FALLBACK_SERVER_URL)
        val previous = keys.associateWith { prefs.getString(it, null) }
        if (!prefs.edit().putString(KEY_SERVER_URL, active).putString(KEY_PRIMARY_SERVER_URL, primary)
                .putString(KEY_FALLBACK_SERVER_URL, fallback).commit()) {
            // commit(false) may already change preference memory. Do not publish that plan.
            prefs.edit().also { editor -> previous.forEach { (key, value) -> editor.putString(key, value) } }.apply()
            ++serverUrlRevision
            throw IOException("Cannot persist management routes")
        }
        ++serverUrlRevision
    }

    @Synchronized
    fun getServerUrl(): String = prefs.getString(KEY_SERVER_URL, "") ?: ""

    @Synchronized
    fun saveServerUrl(url: String) {
        prefs.edit().putString(KEY_SERVER_URL, url.trimEnd('/'))
            .putString(KEY_PRIMARY_SERVER_URL, url.trimEnd('/')).putString(KEY_FALLBACK_SERVER_URL, null).apply()
        ++serverUrlRevision
    }

    /** Возвращает текущий access token без проверки срока истечения (для заголовков HTTP). */
    @Synchronized
    fun getToken(): String? = prefs.getString(KEY_ACCESS_TOKEN, null)

    /**
     * Возвращает свежий access token, обновляя его через refresh endpoint
     * если осталось < 5 минут до истечения.
     *
     * Thread-safe: Mutex гарантирует один refresh-запрос при параллельных вызовах.
     */
    suspend fun getFreshToken(): String? = tokenMutex.withLock { getFreshTokenLocked(getServerUrl()) }

    internal suspend fun getFreshTokenForRoute(plan: ConnectionRoutes, url: String): String? = tokenMutex.withLock {
        synchronized(this@AuthTokenStore) {
            check(plan.revision == serverUrlRevision && url in plan.urls) { "Management route changed" }
        }
        getFreshTokenLocked(url)
    }

    private suspend fun getFreshTokenLocked(serverUrl: String): String? {
        val accessToken = prefs.getString(KEY_ACCESS_TOKEN, null) ?: return null
        val expiresAt = prefs.getLong(KEY_ACCESS_TOKEN_EXPIRES_AT, 0L)
        val refreshToken = prefs.getString(KEY_REFRESH_TOKEN, null)
            ?: return accessToken

        // Если токен истекает через > 5 минут — возвращаем без обновления
        if (System.currentTimeMillis() + REFRESH_THRESHOLD_MS < expiresAt) {
            return accessToken
        }

        return try {
            // Only our own deadline falls back. Parent cancellation must stop reconnect/workers.
            withTimeoutOrNull(REFRESH_TIMEOUT_MS) {
                refreshTokenRequest(refreshToken, serverUrl)
            } ?: run {
                Timber.w("Token refresh timed out, using stored token")
                getToken()
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            currentCoroutineContext().ensureActive()
            Timber.w(e, "Token refresh failed, using stored token")
            getToken()
        }
    }

    private suspend fun refreshTokenRequest(refreshToken: String, serverUrl: String): String {
        val requestId = withContext(Dispatchers.IO) {
            synchronized(this@AuthTokenStore) {
                check(prefs.getString(KEY_REFRESH_TOKEN, null) == refreshToken) { "Refresh credentials changed" }
                val saved = prefs.getString(KEY_REFRESH_ROTATION_ID, null)
                val id = saved?.let { UUID.fromString(it).toString() } ?: UUID.randomUUID().toString()
                // Always commit, including retries: a failed commit changes memory too.
                // This also flushes preceding apply() writes before consuming a child token.
                check(prefs.edit().putString(KEY_REFRESH_ROTATION_ID, id).commit()) {
                    "Cannot persist refresh intent"
                }
                id
            }
        }
        val request = Request.Builder()
            .url("$serverUrl/api/v1/devices/refresh")
            .addHeader("Cookie", "refresh_token=$refreshToken")
            .addHeader("X-Refresh-Request-Id", requestId)
            .post(ByteArray(0).toRequestBody("application/json".toMediaType()))
            .build()

        val call = lazyHttpClient.get().forManagementRoute(serverUrl).newCall(request)
        // Per-call transport bound; never change the shared WS client's timeouts.
        call.timeout().timeout(REFRESH_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        val refreshed = suspendCancellableCoroutine<RefreshedTokens> { continuation ->
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    continuation.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    val tokens = try {
                        response.use {
                            if (!continuation.isActive) return
                            readRefreshResponse(it)
                        }
                    } catch (e: Exception) {
                        continuation.resumeWithException(e)
                        return
                    }
                    // The callback owns/closes the body and returns values only. It never
                    // writes credentials, even when a response arrives after cancellation.
                    continuation.resume(tokens)
                }
            })
        }

        withContext(Dispatchers.IO) {
            val context = currentCoroutineContext()
            synchronized(this@AuthTokenStore) {
                context.ensureActive()
                check(prefs.getString(KEY_REFRESH_TOKEN, null) == refreshToken &&
                    prefs.getString(KEY_REFRESH_ROTATION_ID, null) == requestId) {
                    "Refresh credentials changed"
                }
                // Atomic preference edit. A crash before disk persistence leaves the
                // committed parent+intent recoverable; the next consume commits first.
                prefs.edit()
                    .putString(KEY_ACCESS_TOKEN, refreshed.accessToken)
                    .putString(KEY_REFRESH_TOKEN, refreshed.refreshToken)
                    .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, System.currentTimeMillis() + refreshed.expiresIn * 1000)
                    .remove(KEY_REFRESH_ROTATION_ID)
                    .apply()
                ++credentialRevision
            }
        }

        Timber.d("Access token refreshed, expires in ${refreshed.expiresIn}s")
        return refreshed.accessToken
    }

    private data class RefreshedTokens(val accessToken: String, val refreshToken: String, val expiresIn: Long)

    private fun readRefreshResponse(response: Response): RefreshedTokens {
        check(response.isSuccessful) { "Refresh failed: ${response.code}" }
        // FIX E2: Ограничиваем размер body — защита от OOM при огромном ответе
        val body = response.body ?: error("Empty refresh response")
        val source = body.source()
        check(!source.request(MAX_RESPONSE_CHARS.toLong() + 1)) { "Refresh response too large" }
        val bodyStr = source.readUtf8()
        val json = Json.parseToJsonElement(bodyStr).jsonObject
        val newAccessToken = json["access_token"]!!.jsonPrimitive.content
        val expiresIn = json["expires_in"]?.jsonPrimitive?.long ?: 900L
        val newRefreshToken = json["refresh_token"]?.jsonPrimitive?.content
            ?: error("Refresh response is missing rotation token")

        return RefreshedTokens(newAccessToken, newRefreshToken, expiresIn)
    }

    @Synchronized
    fun saveTokens(accessToken: String, refreshToken: String, expiresIn: Long) {
        ++credentialRevision
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_REFRESH_TOKEN, refreshToken)
            .remove(KEY_REFRESH_ROTATION_ID)
            .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, System.currentTimeMillis() + expiresIn * 1000)
            .apply()
    }

    /**
     * Saves a static API key as the agent's auth token (no expiry / no refresh).
     * Used during device enrollment from [com.sphereplatform.agent.ui.SetupActivity].
     */
    @Synchronized
    fun saveApiKey(apiKey: String) {
        ++credentialRevision
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, apiKey)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_REFRESH_ROTATION_ID)
            .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, Long.MAX_VALUE)
            .apply()
    }

    @Synchronized
    fun clearTokens() {
        ++credentialRevision
        prefs.edit()
            .remove(KEY_ACCESS_TOKEN)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_REFRESH_ROTATION_ID)
            .remove(KEY_ACCESS_TOKEN_EXPIRES_AT)
            .apply()
    }

    /**
     * Force next getFreshToken() to refresh via refresh endpoint.
     * Только сбрасывает expiry — не удаляет refresh_token (позволяет обновить access).
     * Вызывается при AUTH_REJECTED (4001) от сервера.
     */
    @Synchronized
    fun clearTokenCache() {
        prefs.edit()
            .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, 0L)
            .apply()
    }

    /**
     * Возвращает device_id если он валидный UUID.
     * Если сохранён невалидный формат (например, fingerprint "android-xxx") —
     * сбрасывает его и возвращает null для повторной регистрации.
     */
    @Synchronized
    fun getDeviceId(): String? {
        val id = prefs.getString(KEY_DEVICE_ID, null) ?: return null
        if (!UUID_REGEX.matches(id)) {
            Timber.w("Невалидный device_id='%s', сбрасываю для повторной регистрации", id)
            prefs.edit().remove(KEY_DEVICE_ID).apply()
            ++credentialRevision
            return null
        }
        return id
    }

    @Synchronized
    fun saveDeviceId(deviceId: String) {
        ++credentialRevision
        prefs.edit().putString(KEY_DEVICE_ID, deviceId).apply()
    }
}
