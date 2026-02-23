package com.sphereplatform.agent.store

import androidx.security.crypto.EncryptedSharedPreferences
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * AuthTokenStore — безопасное хранение JWT токена агента.
 *
 * Использует EncryptedSharedPreferences (AES256-GCM / AES256-SIV).
 * Ключи и значения никогда не хранятся в plaintext.
 *
 * [getFreshToken] проактивно обновляет access token если осталось < 5 мин до истечения.
 * Это гарантирует что first-message WS всегда содержит неистёкший токен.
 */
@Singleton
class AuthTokenStore @Inject constructor(
    private val prefs: EncryptedSharedPreferences,
    private val httpClient: OkHttpClient,
) {
    companion object {
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_REFRESH_TOKEN = "refresh_token"
        private const val KEY_ACCESS_TOKEN_EXPIRES_AT = "access_token_expires_at"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_DEVICE_ID = "device_id"

        private const val REFRESH_THRESHOLD_MS = 5 * 60 * 1000L  // 5 минут
    }

    private val tokenMutex = Mutex()

    fun getServerUrl(): String = prefs.getString(KEY_SERVER_URL, "") ?: ""

    fun saveServerUrl(url: String) {
        prefs.edit().putString(KEY_SERVER_URL, url).apply()
    }

    /** Возвращает текущий access token без проверки срока истечения (для заголовков HTTP). */
    fun getToken(): String? = prefs.getString(KEY_ACCESS_TOKEN, null)

    /**
     * Возвращает свежий access token, обновляя его через refresh endpoint
     * если осталось < 5 минут до истечения.
     *
     * Thread-safe: Mutex гарантирует один refresh-запрос при параллельных вызовах.
     */
    suspend fun getFreshToken(): String? = tokenMutex.withLock {
        val accessToken = prefs.getString(KEY_ACCESS_TOKEN, null) ?: return@withLock null
        val expiresAt = prefs.getLong(KEY_ACCESS_TOKEN_EXPIRES_AT, 0L)
        val refreshToken = prefs.getString(KEY_REFRESH_TOKEN, null)
            ?: return@withLock accessToken

        // Если токен истекает через > 5 минут — возвращаем без обновления
        if (System.currentTimeMillis() + REFRESH_THRESHOLD_MS < expiresAt) {
            return@withLock accessToken
        }

        return@withLock try {
            refreshTokenRequest(refreshToken)
        } catch (e: Exception) {
            Timber.w(e, "Token refresh failed, using existing token")
            accessToken
        }
    }

    private fun refreshTokenRequest(refreshToken: String): String {
        val serverUrl = getServerUrl()
        val request = Request.Builder()
            .url("$serverUrl/api/v1/auth/refresh")
            .addHeader("Cookie", "refresh_token=$refreshToken")
            .post(ByteArray(0).toRequestBody("application/json".toMediaType()))
            .build()

        httpClient.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Refresh failed: ${response.code}" }
            val bodyStr = response.body?.string() ?: error("Empty refresh response")
            val json = Json.parseToJsonElement(bodyStr).jsonObject
            val newAccessToken = json["access_token"]!!.jsonPrimitive.content
            val expiresIn = json["expires_in"]?.jsonPrimitive?.long ?: 900L

            prefs.edit()
                .putString(KEY_ACCESS_TOKEN, newAccessToken)
                .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, System.currentTimeMillis() + expiresIn * 1000)
                .apply()

            // Ротация refresh token если пришёл новый
            json["refresh_token"]?.jsonPrimitive?.content?.let {
                prefs.edit().putString(KEY_REFRESH_TOKEN, it).apply()
            }

            Timber.d("Access token refreshed, expires in ${expiresIn}s")
            return newAccessToken
        }
    }

    fun saveTokens(accessToken: String, refreshToken: String, expiresIn: Long) {
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_REFRESH_TOKEN, refreshToken)
            .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, System.currentTimeMillis() + expiresIn * 1000)
            .apply()
    }

    /**
     * Saves a static API key as the agent's auth token (no expiry / no refresh).
     * Used during device enrollment from [com.sphereplatform.agent.ui.SetupActivity].
     */
    fun saveApiKey(apiKey: String) {
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, apiKey)
            .remove(KEY_REFRESH_TOKEN)
            .putLong(KEY_ACCESS_TOKEN_EXPIRES_AT, Long.MAX_VALUE)
            .apply()
    }

    fun clearTokens() {
        prefs.edit()
            .remove(KEY_ACCESS_TOKEN)
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_ACCESS_TOKEN_EXPIRES_AT)
            .apply()
    }

    fun getDeviceId(): String? = prefs.getString(KEY_DEVICE_ID, null)

    fun saveDeviceId(deviceId: String) {
        prefs.edit().putString(KEY_DEVICE_ID, deviceId).apply()
    }
}
