package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream

class AdbContinuousHandoffTest {
    private fun set(executor: AdbActionExecutor, field: String, value: Any?) {
        AdbActionExecutor::class.java.getDeclaredField(field).also { it.isAccessible = true }.set(executor, value)
    }

    @Test fun `no prior root process needs neither root grant nor shell startup for handoff`() = runBlocking {
        val context = mockk<Context>()
        val executor = AdbActionExecutor(context)
        assertTrue(executor.inputOwnership.claimContinuous("owner_1234"))
        executor.prepareContinuousInput("owner_1234")
        verify(exactly = 0) { context.applicationInfo }
    }

    @Test fun `continuous claim rejects primitive or shell before any process write`() = runBlocking {
        val executor = AdbActionExecutor(mockk<Context>())
        executor.inputOwnership.claimContinuous("owner_1234")
        assertThrows(DeviceInputBusyException::class.java) { executor.tapRaw(10, 20) }
        assertThrows(DeviceInputBusyException::class.java) { executor.keyEvent(4) }
        assertThrows(DeviceInputBusyException::class.java) { executor.claimInputForTask() }
        try { executor.shell("input keyevent 4"); fail("Shell must not run") } catch (_: DeviceInputBusyException) {}
    }

    @Test fun `old input is drained by an owned FIFO acknowledgement not merely a successful flush`() = runBlocking {
        val executor = AdbActionExecutor(mockk<Context>())
        var reply = ByteArrayInputStream(byteArrayOf())
        val output = object : ByteArrayOutputStream() {
            override fun flush() {
                val marker = Regex("sphere_handoff_[a-f0-9]{32}").find(toString("UTF-8"))?.value
                if (marker != null) reply = ByteArrayInputStream("\r\n$marker:0\r\n".toByteArray())
            }
        }
        val process = mockk<Process>()
        every { process.isAlive } returns true
        every { process.inputStream } answers { reply }
        every { process.errorStream } returns ByteArrayInputStream(byteArrayOf())
        set(executor, "rootProcess", process); set(executor, "rootStream", DataOutputStream(output))
        executor.keyEvent(4)
        assertTrue(executor.inputOwnership.claimContinuous("owner_1234"))
        executor.prepareContinuousInput("owner_1234")
        assertTrue(output.toString("UTF-8").startsWith("input keyevent 4\nprintf"))
        assertEquals(1, Regex("sphere_handoff_[a-f0-9]{32}").findAll(output.toString("UTF-8")).count())
        executor.inputOwnership.release("owner_1234", true)
        executor.keyEvent(3)
        assertTrue(output.toString("UTF-8").endsWith("input keyevent 3\n"))
    }

    @Test fun `dead root with pending input is unknown and never reopened as a handoff retry`() = runBlocking {
        val executor = AdbActionExecutor(mockk<Context>())
        val process = mockk<Process>()
        every { process.isAlive } returns false
        set(executor, "rootProcess", process); set(executor, "rootInputPending", true)
        executor.inputOwnership.claimContinuous("owner_1234")
        try { executor.prepareContinuousInput("owner_1234"); fail("Expected unknown") }
        catch (_: RootCommandOutcomeUnknownException) {}
        verify(exactly = 0) { process.outputStream }
    }

    @Test fun `known unknown old input is never bypassed just because its process was removed`() = runBlocking {
        val executor = AdbActionExecutor(mockk<Context>())
        set(executor, "rootInputOutcomeUnknown", true)
        executor.inputOwnership.claimContinuous("owner_1234")
        try { executor.prepareContinuousInput("owner_1234"); fail("Expected unknown") }
        catch (_: RootCommandOutcomeUnknownException) {}
    }
}
