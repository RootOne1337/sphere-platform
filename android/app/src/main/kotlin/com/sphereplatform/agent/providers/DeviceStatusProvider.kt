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

    // FIX AUDIT-1.3: Предыдущие значения для дельта-вычисления CPU usage
    // /proc/stat содержит КУМУЛЯТИВНЫЕ тики, поэтому нужна разница между замерами
    @Volatile private var prevCpuTotal = 0L
    @Volatile private var prevCpuIdle = 0L
    @Volatile private var cachedCpu = 0f
    @Volatile private var cpuExpireAt = 0L

    /**
     * Загрузка CPU за последний интервал (0-100%).
     *
     * FIX AUDIT-1.3: Вычисляет ДЕЛЬТУ между двумя замерами /proc/stat
     * вместо простого деления кумулятивных тиков. Раньше показывал среднюю
     * за всё время работы (~30-40%), теперь — реальную за последний интервал.
     * Результат кешируется на 5 секунд.
     */
    fun getCpuUsage(): Float {
        val now = System.currentTimeMillis()
        if (now < cpuExpireAt) return cachedCpu
        cpuExpireAt = now + 5_000L
        return try {
            val parts = java.io.File("/proc/stat").useLines { lines ->
                lines.first().trim().split("\\s+".toRegex())
            }
            val user = parts[1].toLong()
            val nice = parts[2].toLong()
            val system = parts[3].toLong()
            val idle = parts[4].toLong()
            val iowait = if (parts.size > 5) parts[5].toLong() else 0L
            val total = user + nice + system + idle + iowait

            val deltaTotal = total - prevCpuTotal
            val deltaIdle = (idle + iowait) - prevCpuIdle

            prevCpuTotal = total
            prevCpuIdle = idle + iowait

            // Первый замер (нет предыдущих данных) → 0f, следующий будет точным
            if (deltaTotal <= 0L) 0f
            else {
                cachedCpu = ((deltaTotal - deltaIdle) * 100f / deltaTotal)
                    .coerceIn(0f, 100f)
                cachedCpu
            }
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
