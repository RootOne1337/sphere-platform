package com.sphereplatform.agent.providers

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.PowerManager
import com.sphereplatform.agent.vpn.SphereVpnManager
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
    private val vpnManager: SphereVpnManager,
) {
    // Кеш уровня заряда — обновляем не чаще раз в 30с.
    // registerReceiver() лёгкий, но создаёт IntentFilter на каждый ping (~15с).
    @Volatile private var cachedBattery = -1
    @Volatile private var batteryExpireAt = 0L

    /** Уровень заряда 0–100, -1 если недоступно. Результат кешируется на 30 секунд. */
    fun getBatteryLevel(): Int {
        val now = System.currentTimeMillis()
        if (now < batteryExpireAt) return cachedBattery
        val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val intent = context.registerReceiver(null, filter) ?: return cachedBattery.also { batteryExpireAt = now + 30_000L }
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        cachedBattery = if (level == -1 || scale == -1) -1 else (level * 100 / scale)
        batteryExpireAt = now + 30_000L
        return cachedBattery
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

    /** Используемая системная RAM в MiB (через ActivityManager.MemoryInfo). */
    fun getRamUsageMb(): Long {
        return try {
            val am = context.getSystemService(ActivityManager::class.java)
            val memInfo = ActivityManager.MemoryInfo()
            am.getMemoryInfo(memInfo)
            (memInfo.totalMem - memInfo.availMem) / (1024 * 1024)
        } catch (_: Exception) {
            0L
        }
    }

    /** Экран включён? */
    fun isScreenOn(): Boolean {
        val pm = context.getSystemService(PowerManager::class.java)
        return pm.isInteractive
    }

    /** VPN активен? Делегируется в SphereVpnManager. */
    fun isVpnActive(): Boolean = vpnManager.isActive()
}
