package com.sphereplatform.agent.providers

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.provider.Settings
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * DeviceInfoProvider — предоставляет уникальный идентификатор устройства и метаданные.
 *
 * Получение device_id (в порядке приоритета):
 * 1. Сохранённый в EncryptedSharedPreferences (постоянный после первой генерации)
 * 2. Android ID (может меняться при factory reset)
 * 3. Сгенерированный UUID (fallback)
 */
@Singleton
class DeviceInfoProvider @Inject constructor(
    @ApplicationContext private val context: Context,
    private val authStore: AuthTokenStore,
) {

    @SuppressLint("HardwareIds")
    fun getDeviceId(): String {
        // Возвращаем сохранённый device_id если он уже был создан
        authStore.getDeviceId()?.let { return it }

        // Используем ANDROID_ID как основу
        val androidId = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID
        )

        val deviceId = if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") {
            // 9774d56d682e549c — дефолтный ANDROID_ID на некоторых эмуляторах
            "android-$androidId"
        } else {
            "android-${UUID.randomUUID()}"
        }

        authStore.saveDeviceId(deviceId)
        return deviceId
    }

    fun getDeviceModel(): String = "${Build.MANUFACTURER} ${Build.MODEL}"

    fun getAndroidVersion(): String = Build.VERSION.RELEASE

    fun getSdkInt(): Int = Build.VERSION.SDK_INT
}
