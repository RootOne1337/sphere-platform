package com.sphereplatform.agent.workers

import android.app.Application
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class LogUploadCooldownTest {
    private var wall = 1_800_000_000_000L
    private var elapsed = 10_000L
    private var boot = 2

    private fun cooldown() = LogUploadCooldown(
        RuntimeEnvironment.getApplication(), { wall }, { elapsed }, { boot },
    )

    @Test fun `deadline is shared across worker recreation and unaffected by same boot wall change`() {
        assertTrue(cooldown().record("device-A", "900"))
        wall += 3_600_000
        elapsed += 899_999
        assertTrue(cooldown().isActive("device-a"))
        assertFalse(cooldown().isActive("device-b"))
        elapsed++
        assertFalse(cooldown().isActive("device-a"))
    }

    @Test fun `reboot uses bounded wall deadline`() {
        assertTrue(cooldown().record("device-a", null))
        boot++
        elapsed = 100
        wall += 899_999
        assertTrue(cooldown().isActive("device-a"))
        wall++
        assertFalse(cooldown().isActive("device-a"))
        wall -= 7_200_000
        assertFalse(cooldown().isActive("device-a"))
    }

    @Test fun `invalid headers use default and zero or huge values are bounded`() {
        assertTrue(cooldown().record("device-a", "invalid"))
        elapsed += 899_999
        assertTrue(cooldown().isActive("device-a"))
        elapsed++
        assertFalse(cooldown().isActive("device-a"))

        assertTrue(cooldown().record("device-a", "0"))
        elapsed += 59_999
        assertTrue(cooldown().isActive("device-a"))
        elapsed++
        assertFalse(cooldown().isActive("device-a"))

        assertTrue(cooldown().record("device-a", "999999999999999999999999999999"))
        elapsed += 3_599_999
        assertTrue(cooldown().isActive("device-a"))
        elapsed++
        assertFalse(cooldown().isActive("device-a"))
    }

    @Test fun `http date is converted to a duration at receipt`() {
        wall = 1_704_067_200_000L  // 1 January 2024 at 00:00:00 UTC
        assertTrue(cooldown().record("device-a", "Mon, 1 Jan 2024 00:02:00 GMT"))
        elapsed += 119_999
        assertTrue(cooldown().isActive("device-a"))
        elapsed++
        assertFalse(cooldown().isActive("device-a"))
    }
}
