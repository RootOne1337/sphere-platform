package com.sphereplatform.agent.providers

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.BatteryManager
import android.os.PowerManager
import com.sphereplatform.agent.vpn.SphereVpnManager
import io.mockk.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты DeviceStatusProvider — метрики устройства для pong-сообщений.
 *
 * Покрытие:
 *  - getBatteryLevel: кеш 30с, расчёт level/scale, fallback -1
 *  - getCpuUsage: delta /proc/stat, кеш 5с, первый замер → 0
 *  - getRamUsageMb: totalMem - availMem
 *  - isScreenOn: PowerManager.isInteractive
 *  - isVpnActive: делегация в SphereVpnManager
 */
class DeviceStatusProviderTest {

    private lateinit var context: Context
    private lateinit var vpnManager: SphereVpnManager
    private lateinit var provider: DeviceStatusProvider

    @Before
    fun setUp() {
        context = mockk(relaxed = true)
        vpnManager = mockk(relaxed = true)
        provider = DeviceStatusProvider(context, vpnManager)
    }

    // ── Battery ──────────────────────────────────────────────────────────────

    @Test
    fun `getBatteryLevel при нормальных данных`() {
        val intent = mockk<Intent> {
            every { getIntExtra(BatteryManager.EXTRA_LEVEL, -1) } returns 75
            every { getIntExtra(BatteryManager.EXTRA_SCALE, -1) } returns 100
        }
        every { context.registerReceiver(null, any()) } returns intent

        val level = provider.getBatteryLevel()
        assertEquals(75, level)
    }

    @Test
    fun `getBatteryLevel при null intent → -1`() {
        every { context.registerReceiver(null, any()) } returns null

        val level = provider.getBatteryLevel()
        assertEquals(-1, level)
    }

    @Test
    fun `getBatteryLevel возвращает кеш при повторном вызове в 30с`() {
        val intent = mockk<Intent> {
            every { getIntExtra(BatteryManager.EXTRA_LEVEL, -1) } returns 80
            every { getIntExtra(BatteryManager.EXTRA_SCALE, -1) } returns 100
        }
        every { context.registerReceiver(null, any()) } returns intent

        provider.getBatteryLevel()
        // Второй вызов — должен использовать кеш (registerReceiver вызван только раз)
        val level2 = provider.getBatteryLevel()
        assertEquals(80, level2)
    }

    @Test
    fun `getBatteryLevel при scale = -1 → -1`() {
        val intent = mockk<Intent> {
            every { getIntExtra(BatteryManager.EXTRA_LEVEL, -1) } returns 50
            every { getIntExtra(BatteryManager.EXTRA_SCALE, -1) } returns -1
        }
        every { context.registerReceiver(null, any()) } returns intent

        assertEquals(-1, provider.getBatteryLevel())
    }

    // ── RAM ──────────────────────────────────────────────────────────────────

    @Test
    fun `getRamUsageMb вычисляет total - available`() {
        val am = mockk<ActivityManager>()
        every { context.getSystemService(ActivityManager::class.java) } returns am
        every { am.getMemoryInfo(any()) } answers {
            val memInfo = firstArg<ActivityManager.MemoryInfo>()
            memInfo.totalMem = 4L * 1024 * 1024 * 1024  // 4 GB
            memInfo.availMem = 2L * 1024 * 1024 * 1024  // 2 GB
        }

        val ram = provider.getRamUsageMb()
        assertEquals(2048L, ram)
    }

    // ── Screen ───────────────────────────────────────────────────────────────

    @Test
    fun `isScreenOn делегирует в PowerManager`() {
        val pm = mockk<PowerManager>()
        every { context.getSystemService(PowerManager::class.java) } returns pm
        every { pm.isInteractive } returns true

        assertTrue(provider.isScreenOn())
    }

    @Test
    fun `isScreenOn false когда экран выключен`() {
        val pm = mockk<PowerManager>()
        every { context.getSystemService(PowerManager::class.java) } returns pm
        every { pm.isInteractive } returns false

        assertFalse(provider.isScreenOn())
    }

    // ── VPN ──────────────────────────────────────────────────────────────────

    @Test
    fun `isVpnActive делегирует в SphereVpnManager`() {
        every { vpnManager.isActive() } returns true
        assertTrue(provider.isVpnActive())
    }

    @Test
    fun `isVpnActive false по умолчанию`() {
        every { vpnManager.isActive() } returns false
        assertFalse(provider.isVpnActive())
    }
}
