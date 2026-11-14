package com.sphereplatform.agent.vpn

import android.content.Context
import io.mockk.mockk
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** Exercise the production activation path, rather than a copy of a host regex. */
class KillSwitchManagerTest {
    @Test fun `no endpoint or management allowlist enables a global firewall`() = runBlocking {
        val manager = KillSwitchManager(mockk<Context>())
        for (endpoint in listOf("vpn.example:51820", "[2001:db8::1]:51820", "bad; command")) {
            try {
                manager.enable(endpoint, listOf("localhost", "10.0.0.1"))
                throw AssertionError("Global firewall activation must be unavailable")
            } catch (error: VpnException) {
                assertEquals("vpn_app_scoped_provider_unavailable", error.message)
            }
            assertFalse(manager.isEnabled)
        }
    }
}
