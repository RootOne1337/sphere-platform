package com.sphereplatform.agent.commands

import android.content.Context
import android.content.pm.ApplicationInfo
import io.mockk.*
import kotlinx.coroutines.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class AdbRootClearTest {
    private lateinit var runtime: Runtime
    private lateinit var context: Context
    private lateinit var executor: AdbActionExecutor
    private val inputs = mutableListOf<ByteArrayOutputStream>()
    private val processes = mutableListOf<Process>()
    private var status: Int? = 0
    private val sent = CountDownLatch(1)

    @Before fun setup() {
        runtime = mockk()
        every { runtime.exec("su") } answers {
            var ack = ByteArrayInputStream(byteArrayOf())
            val input = object : ByteArrayOutputStream() {
                override fun flush() {
                    val command = toString("UTF-8")
                    val marker = Regex("sphere_clear_[a-f0-9]{32}").find(command)?.value
                    if (marker != null) {
                        if (status != null) ack = ByteArrayInputStream("\n$marker:$status\n".toByteArray())
                        sent.countDown()
                    }
                }
            }
            val process = mockk<Process>(relaxed = true)
            every { process.outputStream } returns input
            every { process.inputStream } answers { ack }
            every { process.errorStream } returns ByteArrayInputStream(byteArrayOf())
            every { process.isAlive } returns true
            inputs.add(input)
            processes.add(process)
            process
        }
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        context = mockk()
        val application = ApplicationInfo().apply { sourceDir = "/data/app/sphere/base.apk" }
        every { context.applicationInfo } returns application
        executor = AdbActionExecutor(context)
    }

    @After fun cleanup() { unmockkStatic(Runtime::class) }

    @Test fun `selection deletion and typing preserve FIFO ownership of one root session`() = runBlocking {
        executor.tapRaw(42, 30)
        executor.clearFocusedText()
        executor.typeText("after")
        assertEquals(1, inputs.size)
        val wire = inputs.single().toString("UTF-8")
        assertTrue(wire.indexOf("input tap") < wire.indexOf("RootInputBridge clear-focused"))
        assertTrue(wire.indexOf("RootInputBridge clear-focused") < wire.indexOf("input text"))
        assertFalse(wire.contains("keyevent 277"))
        verify(exactly = 0) { processes.single().destroyForcibly() }
    }

    @Test fun `nonzero helper outcome invalidates ownership without replaying clear`() = runBlocking {
        status = 7
        assertThrows(RootCommandOutcomeUnknownException::class.java) {
            runBlocking { executor.clearFocusedText() }
        }
        verify(exactly = 1) { processes.single().destroyForcibly() }
        executor.keyEvent(4)
        assertEquals(2, inputs.size)
        assertEquals(1, Regex("RootInputBridge clear-focused").findAll(inputs[0].toString("UTF-8")).count())
        assertEquals("input keyevent 4\n", inputs[1].toString("UTF-8"))
    }

    @Test fun `cancelled marker wait invalidates the delivered command without a reader thread or file`() = runBlocking {
        status = null
        val job = launch(Dispatchers.IO) { executor.clearFocusedText() }
        assertTrue(sent.await(2, TimeUnit.SECONDS))
        job.cancelAndJoin()
        verify(exactly = 1) { processes.single().destroyForcibly() }
        executor.keyEvent(4)
        assertEquals(2, inputs.size)
        assertFalse(inputs[0].toString("UTF-8").contains("/sdcard"))
        assertFalse(inputs[1].toString("UTF-8").contains("RootInputBridge"))
    }

    @Test fun `invalid APK path and prior cancellation cannot create a privileged session`() {
        context.applicationInfo.sourceDir = "/data/app/bad\n.apk"
        assertThrows(IllegalArgumentException::class.java) { runBlocking { executor.clearFocusedText() } }
        assertTrue(processes.isEmpty())
    }
}
