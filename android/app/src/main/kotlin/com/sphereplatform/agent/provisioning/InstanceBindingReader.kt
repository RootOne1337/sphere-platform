package com.sphereplatform.agent.provisioning

import android.content.Context
import android.content.SharedPreferences
import android.provider.Settings
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Привязка вне данных APK: постоянный адрес виртуальной сетевой карты VM.
 * LDPlayer 9 представляет её как wlan0 с addr_assign_type=0. IP, IMEI, модель,
 * boot ID и рандомизированный Wi-Fi MAC не используются. На устройствах без
 * доступной постоянной карты запасной источник — ANDROID_ID. Побитовые клоны
 * с одинаковыми виртуальными картами и Android ID этим способом неразличимы.
 */
@Singleton
class InstanceBindingReader internal constructor(
    private val prefs: SharedPreferences,
    private val networkSnapshot: () -> String,
    private val androidId: () -> String?,
    private val requireVirtualNic: Boolean = false,
) {
    @Inject constructor(@ApplicationContext context: Context) : this(
        context.getSharedPreferences("sphere_instance_binding", Context.MODE_PRIVATE),
        { readNetworkSnapshot(context) },
        { Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) },
        android.os.Build.SUPPORTED_ABIS.any { it == "x86" || it == "x86_64" },
    )

    private var cached: String? = null

    /** Сырой MAC не передаётся серверу; чтение выполняется один раз на процесс. */
    @Synchronized
    fun read(): String {
        cached?.let { return it }
        val selected = prefs.getString("source_v1", null)
        val addresses = if (selected == "android-id") emptyMap() else parsePermanentAddresses(networkSnapshot())
        if (selected == null && requireVirtualNic && addresses.isEmpty()) {
            throw IOException("Waiting for a permanent virtual network card")
        }
        val source = selected ?: listOf("eth0", "wlan0").firstOrNull { it in addresses } ?: "android-id"
        val value = if (source == "android-id") androidId()?.takeIf {
            it.isNotBlank() && it != "9774d56d682e549c"
        } else addresses[source]
        // После выбора карты её временная недоступность не переключает identity
        // на ANDROID_ID: повторяем проверку после восстановления Android/сети.
        if (value == null) throw IOException("Instance binding source unavailable: $source")
        if (selected == null && !prefs.edit().putString("source_v1", source).commit()) {
            throw IOException("Cannot persist instance binding source")
        }
        return digest("sphere-instance-binding-v1|$source:$value").also { cached = it }
    }

    companion object {
        internal fun parsePermanentAddresses(raw: String): Map<String, String> = buildMap {
            raw.lineSequence().forEach { line ->
                val fields = line.trim().split('|')
                if (fields.size == 3 && fields[0] in listOf("eth0", "wlan0") && fields[1] == "0") {
                    normalizeAddress(fields[2])?.let { put(fields[0], it) }
                }
            }
        }

        internal fun normalizeAddress(raw: String?): String? {
            val value = raw?.trim()?.lowercase() ?: return null
            if (!value.matches(Regex("(?:[0-9a-f]{2}:){5}[0-9a-f]{2}"))) return null
            if (value in setOf("00:00:00:00:00:00", "02:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")) return null
            if (value.take(2).toInt(16) and 1 != 0) return null
            return value
        }

        internal fun digest(value: String): String = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

        private fun readNetworkSnapshot(context: Context): String {
            val direct = listOf("eth0", "wlan0").mapNotNull { name -> runCatching {
                val path = "/sys/class/net/$name"
                "$name|${File("$path/addr_assign_type").readText().trim()}|${File("$path/address").readText().trim()}"
            }.getOrNull() }.joinToString("\n")
            if (parsePermanentAddresses(direct).isNotEmpty()) return direct
            var output: File? = null
            var process: Process? = null
            return try {
                output = File.createTempFile("instance-binding-", ".txt", context.cacheDir)
                // Только фиксированные sysfs-пути; нет внешнего ввода и изменений ОС.
                val command = "for n in eth0 wlan0; do printf '%s|' \"\$n\"; " +
                    "tr -d '\\n' < /sys/class/net/\$n/addr_assign_type; printf '|'; " +
                    "cat /sys/class/net/\$n/address; done"
                process = ProcessBuilder("su", "-c", command).redirectErrorStream(true).redirectOutput(output).start()
                if (!process.waitFor(3, TimeUnit.SECONDS)) direct else output.inputStream().use {
                    val bytes = ByteArray(2048)
                    val count = it.read(bytes)
                    if (count > 0) String(bytes, 0, count, Charsets.UTF_8) else direct
                }
            } catch (_: IOException) { direct } finally {
                process?.let { if (it.isAlive) it.destroyForcibly() }
                output?.delete()
            }
        }
    }
}
