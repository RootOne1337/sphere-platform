package com.sphereplatform.agent.root

import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.IOException
import java.util.concurrent.TimeUnit

class RootScreenCapturePermissionTest {
    @get:Rule val folder = TemporaryFolder()
    private val process = mockk<Process>(relaxed = true)
    private var commands = mutableListOf<List<String>>()

    private fun permission(
        output: String = "PROJECT_MEDIA: allow; time=+1s",
        exit: Int = 0,
        finished: Boolean = true,
        packageName: String = "com.sphereplatform.agent.pilot.debug",
        userId: Int = 0,
    ): RootScreenCapturePermission {
        every { process.waitFor(8, TimeUnit.SECONDS) } returns finished
        every { process.exitValue() } returns exit
        every { process.isAlive } returns !finished
        return RootScreenCapturePermission(packageName, userId, folder.root) { command, file ->
            commands.add(command)
            file.writeText(output)
            process
        }
    }

    @Test fun `grants only this package and verifies actual app op without adb`() = runBlocking {
        assertTrue(permission().prepare())
        assertEquals(listOf(listOf("su", "-c", "cmd appops set --user 0 com.sphereplatform.agent.pilot.debug PROJECT_MEDIA allow && cmd appops get --user 0 com.sphereplatform.agent.pilot.debug PROJECT_MEDIA")), commands)
        assertEquals(0, folder.root.listFiles()!!.size)
    }

    @Test fun `uses the app Android user instead of modifying user zero`() = runBlocking {
        assertTrue(permission(userId = 10).prepare())
        assertTrue(commands.single()[2].contains("--user 10"))
        assertFalse(commands.single()[2].contains("--user 0"))
    }

    @Test fun `vendor exit zero without allow is not success`() = runBlocking {
        for (output in listOf("", "Error: unknown operation", "PROJECT_MEDIA: deny", "PROJECT_MEDIA: default", "OTHER_OP: allow", "PROJECT_MEDIA: allowed")) {
            assertFalse(output, permission(output).prepare())
        }
    }

    @Test fun `failed root exits cannot report granted even with allow text`() = runBlocking {
        assertFalse(permission(exit = 1).prepare())
    }

    @Test fun `hung su is killed and diagnostic file removed`() = runBlocking {
        assertFalse(permission(finished = false).prepare())
        verify(atLeast = 1) { process.destroyForcibly() }
        verify(exactly = 0) { process.exitValue() }
        assertEquals(0, folder.root.listFiles()!!.size)
    }

    @Test fun `missing su retains normal consent flow and cleans temporary output`() = runBlocking {
        val permission = RootScreenCapturePermission("com.sphereplatform.agent", 0, folder.root) { _, _ ->
            throw IOException("su missing")
        }
        assertFalse(permission.prepare())
        assertEquals(0, folder.root.listFiles()!!.size)
    }

    @Test fun `invalid package or user never spawns a process`() = runBlocking {
        assertFalse(permission(packageName = "com.example;cmd").prepare())
        assertFalse(permission(userId = -1).prepare())
        assertTrue(commands.isEmpty())
    }

    @Test fun `diagnostic parsing is bounded and does not trust a late marker`() = runBlocking {
        assertFalse(permission("x".repeat(4096) + "\nPROJECT_MEDIA: allow").prepare())
    }
}
