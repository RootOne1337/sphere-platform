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
 * Clone-resistant binding using stable VM serial plus permanent virtual NIC.
 * No IP, IMEI, model, boot ID or app-private cloneable seed is used. A bitwise
 * clone that also duplicates both hardware values remains indistinguishable and
 * must be provisioned with a unique hypervisor identity.
 */
@Singleton
class InstanceBindingReader internal constructor(
    private val prefs: SharedPreferences,
    private val networkSnapshot: () -> String,
    private val androidId: () -> String?,
    private val requireVirtualNic: Boolean = false,
    private val virtualSerial: () -> String? = { null },
) {
    @Inject constructor(@ApplicationContext context: Context) : this(
        context.getSharedPreferences("sphere_instance_binding", Context.MODE_PRIVATE),
        { readNetworkSnapshot(context) },
        { Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) },
        android.os.Build.SUPPORTED_ABIS.any { it == "x86" || it == "x86_64" },
        { readVirtualSerial() },
    )

    private data class Binding(val value: String, val version: Int)

    private var cached: Binding? = null

    /** Raw hardware values stay on-device; only the SHA-256 binding is sent. */
    @Synchronized
    fun read(): String = binding().value

    /** Sent with registration so the server can migrate v1 clones exactly once. */
    @Synchronized
    fun version(): Int = binding().version

    @Synchronized
    private fun binding(): Binding {
        cached?.let { return it }
        val persistedSource = prefs.getString("source_v2", null)
        val emulatorBinding = requireVirtualNic || persistedSource?.startsWith("emulator_") == true
        val selected = persistedSource?.takeUnless { requireVirtualNic && it == "android_id" }
        val addresses = if (emulatorBinding) parsePermanentAddresses(networkSnapshot()) else emptyMap()
        val serial = if (emulatorBinding) normalizeVirtualSerial(virtualSerial()) else null
        val source = selected ?: if (emulatorBinding) {
            when {
                serial != null && "eth0" in addresses -> "emulator_serial_eth0"
                serial != null && "wlan0" in addresses -> "emulator_serial_wlan0"
                serial != null -> "emulator_serial"
                "eth0" in addresses -> "emulator_eth0"
                "wlan0" in addresses -> "emulator_wlan0"
                else -> throw IOException("Waiting for stable emulator identity")
            }
        } else {
            "android_id"
        }

        val material = when (source) {
            "emulator_serial_eth0" -> "serial:${requireSerial(serial)}|nic:${requireAddress(addresses, "eth0")}"
            "emulator_serial_wlan0" -> "serial:${requireSerial(serial)}|nic:${requireAddress(addresses, "wlan0")}"
            "emulator_serial" -> "serial:${requireSerial(serial)}"
            "emulator_eth0" -> "nic:${requireAddress(addresses, "eth0")}"
            "emulator_wlan0" -> "nic:${requireAddress(addresses, "wlan0")}"
            "android_id" -> "android-id:${androidId()?.takeIf {
                it.isNotBlank() && it != "9774d56d682e549c"
            } ?: throw IOException("Android ID unavailable for instance binding") }"
            else -> throw IOException("Unsupported instance binding source")
        }

        if (selected == null && !prefs.edit().putString("source_v2", source).commit()) {
            throw IOException("Cannot persist instance binding source")
        }
        return Binding(digest("sphere-instance-binding-v2|$source|$material"), CURRENT_VERSION)
            .also { cached = it }
    }

    companion object {
        const val CURRENT_VERSION = 2

        private fun requireSerial(value: String?): String = value
            ?: throw IOException("Stable emulator serial unavailable; retrying identity check")

        private fun requireAddress(addresses: Map<String, String>, interfaceName: String): String =
            addresses[interfaceName]
                ?: throw IOException("Stable emulator network identity unavailable; retrying identity check")

        internal fun normalizeVirtualSerial(raw: String?): String? {
            val value = raw?.trim()?.lowercase() ?: return null
            if (value.length !in 3..128 || value in setOf("unknown", "none", "null", "n/a", "unset")) return null
            if (value.all { it == '0' || it == ':' || it == '-' }) return null
            if (!value.matches(Regex("[a-z0-9][a-z0-9._:-]{1,127}"))) return null
            return value
        }

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

        private fun readVirtualSerial(): String? {
            for (property in listOf("ro.boot.serialno", "ro.serialno")) {
                val value = runCatching {
                    val process = ProcessBuilder("/system/bin/getprop", property)
                        .redirectErrorStream(true).start()
                    if (!process.waitFor(1500, TimeUnit.MILLISECONDS)) {
                        process.destroyForcibly()
                        null
                    } else {
                        process.inputStream.bufferedReader().use { it.readLine()?.trim() }
                    }
                }.getOrNull()
                normalizeVirtualSerial(value)?.let { return it }
            }
            return null
        }

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
