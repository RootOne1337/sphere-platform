package com.sphereplatform.agent.provisioning

import android.content.Context
import android.content.SharedPreferences
import android.provider.Settings
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Clone-resistant binding using the emulator's VM serial, read through Android's
 * unprivileged getprop interface. Ambiguous MAC-only fallback is intentionally
 * rejected: a cloned emulator image can duplicate both its Android ID and NIC.
 * A bitwise VM clone that also duplicates the serial still requires a unique
 * hypervisor identity; the app cannot synthesize one safely from copied state.
 */
@Singleton
class InstanceBindingReader internal constructor(
    private val prefs: SharedPreferences,
    private val androidId: () -> String?,
    private val isEmulator: Boolean = false,
    private val virtualSerial: () -> String? = { null },
) {
    @Inject constructor(@ApplicationContext context: Context) : this(
        context.getSharedPreferences("sphere_instance_binding", Context.MODE_PRIVATE),
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
        val emulatorBinding = isEmulator || persistedSource?.startsWith("emulator_") == true
        val serial = if (emulatorBinding) normalizeVirtualSerial(virtualSerial()) else null
        val source = if (emulatorBinding) {
            requireSerial(serial)
            "emulator_serial"
        } else {
            persistedSource ?: "android_id"
        }

        val material = when (source) {
            "emulator_serial" -> "serial:${requireSerial(serial)}"
            "android_id" -> "android-id:${androidId()?.takeIf {
                it.isNotBlank() && it != "9774d56d682e549c"
            } ?: throw IOException("Android ID unavailable for instance binding") }"
            else -> throw IOException("Unsupported instance binding source")
        }

        if (persistedSource != source && !prefs.edit().putString("source_v2", source).commit()) {
            throw IOException("Cannot persist instance binding source")
        }
        return Binding(digest("sphere-instance-binding-v2|$source|$material"), CURRENT_VERSION)
            .also { cached = it }
    }

    companion object {
        const val CURRENT_VERSION = 2

        private fun requireSerial(value: String?): String = value
            ?: throw IOException("Stable emulator VM serial unavailable; refusing ambiguous clone identity")

        internal fun normalizeVirtualSerial(raw: String?): String? {
            val value = raw?.trim()?.lowercase() ?: return null
            if (value.length !in 3..128 || value in setOf("unknown", "none", "null", "n/a", "unset")) return null
            if (value.all { it == '0' || it == ':' || it == '-' }) return null
            if (!value.matches(Regex("[a-z0-9][a-z0-9._:-]{1,127}"))) return null
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
    }
}
