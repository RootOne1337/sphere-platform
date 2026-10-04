package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.*
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/** Missing root must reject an explicit privileged action, not construction of the agent. */
class AdbRootAvailabilityTest {
    private lateinit var runtime: Runtime

    @Before fun setup() {
        runtime = mockk()
        every { runtime.exec("su") } throws IOException("No su binary on this phone")
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
    }

    @After fun cleanup() { unmockkStatic(Runtime::class) }

    @Test fun `agent command component can start without a root executable`() {
        AdbActionExecutor(mockk<Context>())
        verify(exactly = 0) { runtime.exec("su") }
    }

    @Test fun `closing an unused component never starts root`() {
        val executor = AdbActionExecutor(mockk<Context>())
        executor.closeRootSession()
        verify(exactly = 0) { runtime.exec("su") }
    }

    @Test fun `explicit privileged input still fails when root is unavailable`() {
        val executor = AdbActionExecutor(mockk<Context>())
        assertThrows(IOException::class.java) { executor.keyEvent(4) }
        verify(exactly = 1) { runtime.exec("su") }
    }

    @Test fun `close is idempotent and only a subsequent explicit action opens another session`() {
        val firstInput = ByteArrayOutputStream()
        val nextInput = ByteArrayOutputStream()
        val first = mockk<Process>()
        val next = mockk<Process>()
        every { first.outputStream } returns firstInput
        every { first.isAlive } returns true
        every { first.waitFor(250, TimeUnit.MILLISECONDS) } returns true
        every { next.outputStream } returns nextInput
        every { next.isAlive } returns true
        every { runtime.exec("su") } returnsMany listOf(first, next)

        val executor = AdbActionExecutor(mockk<Context>())
        executor.keyEvent(4)
        executor.closeRootSession()
        executor.closeRootSession()
        assertEquals("input keyevent 4\nexit\n", firstInput.toString("UTF-8"))
        verify(exactly = 1) { runtime.exec("su") }
        verify(exactly = 0) { first.destroyForcibly() }

        executor.keyEvent(66)
        assertEquals("input keyevent 66\n", nextInput.toString("UTF-8"))
        verify(exactly = 2) { runtime.exec("su") }
    }

    @Test fun `a dead session closes its old stream before the next explicit action`() {
        var oldClosed = false
        val firstInput = object : ByteArrayOutputStream() {
            override fun close() { oldClosed = true; super.close() }
        }
        val nextInput = ByteArrayOutputStream()
        val first = mockk<Process>()
        val next = mockk<Process>()
        every { first.outputStream } returns firstInput
        every { first.isAlive } returns false
        every { next.outputStream } answers { assertTrue(oldClosed); nextInput }
        every { next.isAlive } returns true
        every { runtime.exec("su") } returnsMany listOf(first, next)

        val executor = AdbActionExecutor(mockk<Context>())
        executor.keyEvent(4)
        executor.keyEvent(66)
        assertEquals("input keyevent 4\n", firstInput.toString("UTF-8"))
        assertEquals("input keyevent 66\n", nextInput.toString("UTF-8"))
        verify(exactly = 2) { runtime.exec("su") }
    }

    @Test fun `failure acquiring stdin destroys the newly owned process without writing input`() {
        val first = mockk<Process>()
        every { first.outputStream } throws IOException("stdin unavailable")
        every { first.destroyForcibly() } returns first
        every { runtime.exec("su") } returns first

        val executor = AdbActionExecutor(mockk<Context>())
        assertThrows(IOException::class.java) { executor.keyEvent(4) }
        executor.closeRootSession()
        verify(exactly = 1) { runtime.exec("su") }
        verify(exactly = 1) { first.destroyForcibly() }
    }
}
