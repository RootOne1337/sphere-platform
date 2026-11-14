package com.sphereplatform.agent.workers

import android.content.Context
import android.os.SystemClock
import android.provider.Settings
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

/** The quota is shared by all management routes for the assigned device. */
internal class LogUploadCooldown(
    private val context: Context,
    private val wallTime: () -> Long = System::currentTimeMillis,
    private val elapsedTime: () -> Long = SystemClock::elapsedRealtime,
    private val bootCount: () -> Int = {
        try {
            Settings.Global.getInt(context.contentResolver, Settings.Global.BOOT_COUNT, -1)
        } catch (_: SecurityException) {
            -1
        }
    },
) {
    private val prefs = context.getSharedPreferences("sphere_log_upload_cooldown", Context.MODE_PRIVATE)

    fun isActive(deviceId: String): Boolean {
        if (prefs.getString("device_id", null) != deviceId.lowercase(Locale.ROOT)) return false
        val boot = bootCount()
        val remaining = if (boot >= 0 && prefs.getInt("boot_count", -1) == boot) {
            prefs.getLong("elapsed_until", 0L) - elapsedTime()
        } else {
            prefs.getLong("wall_until", 0L) - wallTime()
        }
        // Ignore implausibly distant wall deadlines after a reboot or clock reset.
        return remaining in 1..MAX_DELAY_MS
    }

    fun record(deviceId: String, retryAfter: String?): Boolean {
        val now = wallTime()
        val delayMs = delayMs(retryAfter, now)
        return prefs.edit()
            .putString("device_id", deviceId.lowercase(Locale.ROOT))
            .putInt("boot_count", bootCount())
            .putLong("wall_until", now + delayMs)
            .putLong("elapsed_until", elapsedTime() + delayMs)
            .commit()
    }

    private companion object {
        const val DEFAULT_DELAY_SECONDS = 900L
        const val MIN_DELAY_SECONDS = 60L
        const val MAX_DELAY_SECONDS = 3600L
        const val MAX_DELAY_MS = MAX_DELAY_SECONDS * 1000L

        fun delayMs(retryAfter: String?, now: Long): Long {
            val value = retryAfter?.trim().orEmpty()
            if (value.isNotEmpty() && value.all { it in '0'..'9' }) {
                val seconds = value.trimStart('0').ifEmpty { "0" }.toLongOrNull() ?: MAX_DELAY_SECONDS
                return seconds.coerceIn(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS) * 1000L
            }
            val requested = try {
                val requestedAt = ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME)
                    .toInstant().toEpochMilli()
                Math.subtractExact(requestedAt, now)
            } catch (_: DateTimeParseException) {
                DEFAULT_DELAY_SECONDS * 1000L
            } catch (_: ArithmeticException) {
                DEFAULT_DELAY_SECONDS * 1000L
            }
            return requested.coerceIn(MIN_DELAY_SECONDS * 1000L, MAX_DELAY_MS)
        }
    }
}
