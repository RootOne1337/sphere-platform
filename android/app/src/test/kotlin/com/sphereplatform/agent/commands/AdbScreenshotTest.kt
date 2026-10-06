package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.*
import kotlinx.coroutines.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class AdbScreenshotTest {
    @get:Rule val temporary = TemporaryFolder()
    private lateinit var runtime: Runtime
    private lateinit var executor: AdbActionExecutor
    private val inputs = mutableListOf<ByteArrayOutputStream>()
    private val processes = mutableListOf<Process>()
    private var status: Int? = 0
    private var valid = true
    private val sent = CountDownLatch(1)

    @Before fun setup() {
        runtime = mockk()
        every { runtime.exec("su") } answers {
            var ack = ByteArrayInputStream(byteArrayOf())
            val input = object : ByteArrayOutputStream() {
                override fun flush() {
                    val command = toString("UTF-8")
                    val marker = Regex("sphere_capture_[a-f0-9]{32}").find(command)?.value
                    if (marker != null) {
                        val path = Regex("screencap -p '([^']+)'").find(command)!!.groupValues[1]
                        File(path).writeBytes(if (valid) screenshotFixture() else byteArrayOf())
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
            inputs.add(input); processes.add(process)
            process
        }
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        val context = mockk<Context>()
        every { context.cacheDir } returns temporary.root
        executor = AdbActionExecutor(context)
    }

    @After fun cleanup() { unmockkStatic(Runtime::class) }

    @Test fun `capture waits for same FIFO session acknowledgement and original file validation`() = runBlocking {
        executor.keyEvent(3)
        val file = File(executor.takeScreenshot())
        assertArrayEquals(screenshotFixture(), file.readBytes())
        assertEquals(1, inputs.size)
        val wire = inputs.single().toString("UTF-8")
        assertTrue(wire.indexOf("input keyevent") < wire.indexOf("screencap -p"))
        assertFalse(wire.contains("/sdcard"))
        verify(exactly = 0) { processes.single().destroyForcibly() }
    }

    @Test fun `failed capture cannot report a path or replay command`() = runBlocking {
        status = 1
        assertThrows(RootCommandOutcomeUnknownException::class.java) { runBlocking { executor.takeScreenshot() } }
        assertEquals(0, File(temporary.root, "dag-screenshots-v1").listFiles()!!.size)
        verify(exactly = 1) { processes.single().destroyForcibly() }
        executor.keyEvent(4)
        assertEquals(2, inputs.size)
        assertEquals(1, Regex("screencap -p").findAll(inputs[0].toString("UTF-8")).count())
        assertEquals("input keyevent 4\n", inputs[1].toString("UTF-8"))
    }

    @Test fun `successful shell marker with empty PNG still fails file verification`() = runBlocking {
        valid = false
        assertThrows(java.io.IOException::class.java) { runBlocking { executor.takeScreenshot() } }
        assertEquals(0, File(temporary.root, "dag-screenshots-v1").listFiles()!!.size)
        verify(exactly = 0) { processes.single().destroyForcibly() }
    }

    @Test fun `cancelled capture invalidates delivered root ownership and cleans owned staging`() = runBlocking {
        status = null
        val job = launch(Dispatchers.IO) { executor.takeScreenshot() }
        assertTrue(sent.await(2, TimeUnit.SECONDS))
        job.cancelAndJoin()
        verify(exactly = 1) { processes.single().destroyForcibly() }
        assertEquals(0, File(temporary.root, "dag-screenshots-v1").listFiles()!!.size)
    }
}
