package com.sphereplatform.agent.providers

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.provider.Settings
import com.sphereplatform.agent.provisioning.CloneDetector
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
 * 2. Сервер-назначенный device_id (после авто-регистрации через DeviceRegistrationClient)
 * 3. Android ID (может совпадать у клонов — дополняем fingerprint)
 * 4. Сгенерированный UUID (fallback)
 *
 * Для клонов LDPlayer: ANDROID_ID одинаков — используем CloneDetector.getFingerprint()
 * как часть уникализации. Fingerprint учитывает app_instance_id, уникальный для каждого клона.
 */
@Singleton
class DeviceInfoProvider @Inject constructor(
    @ApplicationContext private val context: Context,
    private val authStore: AuthTokenStore,
    private val cloneDetector: CloneDetector,
) {

    @SuppressLint("HardwareIds")
    fun getDeviceId(): String {
        // 1. Возвращаем сохранённый device_id (в т.ч. назначенный сервером)
        authStore.getDeviceId()?.let { return it }

        // 2. Для эмуляторов: используем fingerprint от CloneDetector (clone-safe)
        if (cloneDetector.isEmulator()) {
            val fingerprint = cloneDetector.getFingerprint()
            val deviceId = "emu-${fingerprint.take(16)}"
            authStore.saveDeviceId(deviceId)
            return deviceId
        }

        // 3. Физические устройства: ANDROID_ID
        val androidId = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID,
        )

        val deviceId = if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") {
            "android-$androidId"
        } else {
            "android-${UUID.randomUUID()}"
        }

        authStore.saveDeviceId(deviceId)
        return deviceId
    }

    /**
     * Fingerprint устройства для автоматической регистрации.
     * Делегирует в CloneDetector для clone-safe уникальности.
     */
    fun getFingerprint(): String = cloneDetector.getFingerprint()

    /**
     * Тип устройства для регистрации (ldplayer, physical, genymotion, nox).
     */
    fun getDeviceType(): String = cloneDetector.getDeviceType()

    fun getDeviceModel(): String = "${Build.MANUFACTURER} ${Build.MODEL}"

    fun getAndroidVersion(): String = Build.VERSION.RELEASE

    fun getSdkInt(): Int = Build.VERSION.SDK_INT
}
