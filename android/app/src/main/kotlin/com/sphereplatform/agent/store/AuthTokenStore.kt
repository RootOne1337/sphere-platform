package com.sphereplatform.agent.store

import androidx.security.crypto.EncryptedSharedPreferences
import javax.inject.Inject
import javax.inject.Singleton

/**
 * AuthTokenStore — безопасное хранение JWT токена агента.
 *
 * Использует EncryptedSharedPreferences (AES256-GCM / AES256-SIV).
 * Ключи и значения никогда не хранятся в plaintext.
 */
@Singleton
class AuthTokenStore @Inject constructor(
    private val prefs: EncryptedSharedPreferences,
) {
    companion object {
        private const val KEY_TOKEN = "auth_token"
        private const val KEY_DEVICE_ID = "device_id"
    }

    fun getToken(): String? = prefs.getString(KEY_TOKEN, null)

    fun saveToken(token: String) {
        prefs.edit().putString(KEY_TOKEN, token).apply()
    }

    fun clearToken() {
        prefs.edit().remove(KEY_TOKEN).apply()
    }

    fun getDeviceId(): String? = prefs.getString(KEY_DEVICE_ID, null)

    fun saveDeviceId(deviceId: String) {
        prefs.edit().putString(KEY_DEVICE_ID, deviceId).apply()
    }
}
