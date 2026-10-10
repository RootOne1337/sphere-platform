package com.sphereplatform.agent.root

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RootAutoStartPolicyTest {
    @Test
    fun `root setup is limited to the owned package and notification permission`() {
        val commands = RootAutoStart.rootSetupCommands("com.example.agent", 35)

        assertTrue(commands.any { it.contains("deviceidle whitelist +com.example.agent") })
        assertTrue(commands.any { it.contains("RUN_ANY_IN_BACKGROUND") })
        assertTrue(commands.any { it.contains("POST_NOTIFICATIONS") })
        assertFalse(commands.any { it.contains("set-stopped-state") })
        assertFalse(commands.any { it.contains("pm enable") })
        assertFalse(commands.any(::isSystemWideMutation))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `root setup rejects shell metacharacters in a package name`() {
        RootAutoStart.rootSetupCommands("com.example;reboot", 35)
    }

    private fun isSystemWideMutation(command: String): Boolean =
        listOf("setenforce", "supolicy", "mount", "/system/", "init.rc", "sed -i", "nohup", "while true")
            .any { marker -> command.contains(marker, ignoreCase = true) }
}
