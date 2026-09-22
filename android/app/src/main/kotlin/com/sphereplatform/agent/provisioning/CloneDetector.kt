package com.sphereplatform.agent.provisioning

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.provider.Settings
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * CloneDetector — обнаружение и идентификация клонов LDPlayer/эмуляторов.
 *
 * Проблема: все клоны LDPlayer разделяют одинаковый ANDROID_ID, Build.SERIAL,
 * Build.MODEL и другие стандартные идентификаторы. Без дополнительных мер
 * невозможно отличить один клон от другого.
 *
 * Совместимый fingerprint шаблона из нескольких слоёв:
 * 1. app_instance_id — уникальный UUID, сгенерированный при первой установке APK
 * 2. ANDROID_ID — может совпадать у клонов, но полезен как часть хеша
 * 3. Build.FINGERPRINT — содержит информацию о системном образе
 * 4. Доступный приложению серийный номер и параметры образа
 *
 * Финальный fingerprint = SHA-256(app_instance_id + android_id + build_fingerprint + ...)
 * Сам по себе НЕ различает копии /data. Разделение выполняет сервер по
 * instance_binding из [InstanceBindingReader], до подключения через
 * [InstanceRegistrationGuard]. После миграции fingerprint фиксируется:
 * смена модели, Android ID или сборки не пересоздаёт регистрацию.
 */
@Singleton
class CloneDetector @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    companion object {
        private const val PREFS_NAME = "sphere_clone_detector"
        private const val KEY_APP_INSTANCE_ID = "app_instance_id"
        private const val KEY_TEMPLATE_FINGERPRINT = "template_fingerprint_v1"
    }

    /**
     * Совместимый fingerprint шаблона, сохраняющий старую серверную карточку.
     * Детерминистичен: повторные вызовы возвращают одинаковое значение.
     */
    @Synchronized
    fun getFingerprint(): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.getString(KEY_TEMPLATE_FINGERPRINT, null)?.let { return it }
        val components = buildList {
            add("instance:${getOrCreateInstanceId()}")
            add("android_id:${getAndroidId()}")
            add("build_fp:${Build.FINGERPRINT}")
            add("serial:${getSerialNumber()}")
            add("board:${Build.BOARD}")
            add("bootloader:${Build.BOOTLOADER}")
            add("host:${Build.HOST}")
        }

        val raw = components.joinToString("|")
        val hash = sha256(raw)
        check(prefs.edit().putString(KEY_TEMPLATE_FINGERPRINT, hash).commit()) {
            "Cannot persist template fingerprint"
        }

        Timber.d("CloneDetector: fingerprint=$hash (components=${components.size})")
        return hash
    }

    /**
     * Определяет, является ли устройство эмулятором/клоном LDPlayer.
     */
    fun isEmulator(): Boolean {
        val indicators = listOf(
            Build.FINGERPRINT.contains("generic", ignoreCase = true),
            Build.MODEL.contains("sdk", ignoreCase = true),
            Build.MODEL.contains("emulator", ignoreCase = true),
            Build.MANUFACTURER.contains("Genymotion", ignoreCase = true),
            Build.PRODUCT.contains("sdk", ignoreCase = true),
            Build.PRODUCT.contains("vbox", ignoreCase = true),
            Build.HARDWARE.contains("goldfish", ignoreCase = true),
            Build.HARDWARE.contains("ranchu", ignoreCase = true),
        )
        return indicators.any { it }
    }

    /**
     * Определяет тип устройства для регистрации.
     */
    fun getDeviceType(): String = when {
        Build.PRODUCT.contains("ldplayer", ignoreCase = true) ||
            Build.MANUFACTURER.contains("ldplayer", ignoreCase = true) -> "ldplayer"
        Build.MANUFACTURER.contains("Genymotion", ignoreCase = true) -> "genymotion"
        Build.PRODUCT.contains("nox", ignoreCase = true) -> "nox"
        isEmulator() -> "ldplayer" // По умолчанию для LDPlayer (основной эмулятор)
        else -> "physical"
    }

    // ── Компоненты fingerprint ──────────────────────────────────────────────

    /**
     * Уникальный ID экземпляра приложения.
     * Генерируется один раз при первом запуске и сохраняется в SharedPreferences.
     * Полная копия VM копирует и этот ID; он обозначает общий шаблон.
     */
    private fun getOrCreateInstanceId(): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.getString(KEY_APP_INSTANCE_ID, null)?.let { return it }

        val newId = java.util.UUID.randomUUID().toString()
        check(prefs.edit().putString(KEY_APP_INSTANCE_ID, newId).commit()) { "Cannot persist instance seed" }
        Timber.i("CloneDetector: generated new app_instance_id=$newId")
        return newId
    }

    @SuppressLint("HardwareIds")
    private fun getAndroidId(): String {
        return Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID,
        ) ?: "unknown"
    }

    @SuppressLint("HardwareIds")
    @Suppress("DEPRECATION")
    private fun getSerialNumber(): String = runCatching {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Build.getSerial()
        } else {
            Build.SERIAL
        }
    }.getOrDefault("unknown")

    private fun sha256(input: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(input.toByteArray(Charsets.UTF_8))
        return hash.joinToString("") { "%02x".format(it) }
    }
}
