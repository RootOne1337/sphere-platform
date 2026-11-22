package com.sphereplatform.agent.vpn

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class VpnExecutionPolicyTest {
    @get:Rule val temporary = TemporaryFolder()

    private fun rejected(block: suspend () -> Unit) = runBlocking {
        try {
            block()
            throw AssertionError("Unsafe VPN activation was allowed")
        } catch (error: VpnException) {
            assertEquals("vpn_app_scoped_provider_unavailable", error.message)
        }
    }

    @Test fun `connect cannot replace existing config or execute imported hooks`() {
        val context = mockk<Context>()
        every { context.filesDir } returns temporary.root
        val manager = SphereVpnManager(context)
        val saved = File(temporary.root, "vpn/sphere0.conf")
        saved.writeText("existing-private-config")
        rejected { manager.connect("[Interface]\nPostUp = touch SHOULD_NEVER_EXIST") }
        assertEquals("existing-private-config", saved.readText())
        assertFalse(File(temporary.root, "SHOULD_NEVER_EXIST").exists())
    }

    @Test fun `reconnect rejects before accessing saved config`() {
        val context = mockk<Context>()
        every { context.filesDir } returns temporary.root
        val manager = SphereVpnManager(context)
        rejected { manager.reconnect() }
        assertFalse(File(temporary.root, "vpn/sphere0.conf").exists())
    }

    @Test fun `global kill switch cannot touch Android firewall`() {
        val context = mockk<Context>()
        val manager = KillSwitchManager(context)
        rejected { manager.enable("203.0.113.1:51820", listOf("management.example")) }
        assertFalse(manager.isEnabled)
        verify(exactly = 0) { context.getSystemService(any<String>()) }
    }
}
