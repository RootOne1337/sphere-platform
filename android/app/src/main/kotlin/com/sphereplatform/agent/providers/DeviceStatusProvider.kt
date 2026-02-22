package com.sphereplatform.agent.providers

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.PowerManager
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * DeviceStatusProvider — агрегирует метрики устройства для pong-сообщений.
 *
 * Вызывается синхронно в handlePingImmediate (не в корутине),
 * поэтому все методы должны быть неблокирующими.
 */
@Singleton
class DeviceStatusProvider @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    /** Уровень заряда 0–100, -1 если недоступно. */
    fun getBatteryLevel(): Int {
        val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val intent = context.registerReceiver(null, filter) ?: return -1
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level == -1 || scale == -1) return -1
        return (level * 100 / scale)
    }

    /** Приближённая загрузка CPU (первая строка /proc/stat), 0–100. */
    fun getCpuUsage(): Float {
        return try {
            val lines = java.io.File("/proc/stat").readLines()
            val parts = lines.first().trim().split("\\s+".toRegex())
            val user = parts[1].toLong()
            val nice = parts[2].toLong()
            val system = parts[3].toLong()
            val idle = parts[4].toLong()
            val total = user + nice + system + idle
            if (total == 0L) 0f else ((total - idle) * 100f / total)
        } catch (_: Exception) {
            0f
        }
    }

    /** RAM занято в MiB. */
    fun getRamUsageMb(): Long {
        return try {
            val runtime = Runtime.getRuntime()
            (runtime.totalMemory() - runtime.freeMemory()) / (1024 * 1024)
        } catch (_: Exception) {
            0L
        }
    }

    /** Экран включён? */
    fun isScreenOn(): Boolean {
        val pm = context.getSystemService(PowerManager::class.java)
        return pm.isInteractive
    }

    /** VPN активен? (SphereVpnManager предоставляет реальное значение после интеграции TZ-06) */
    fun isVpnActive(): Boolean = false
}
