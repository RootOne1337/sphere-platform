package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.*
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.CancellationException
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.util.concurrent.CountDownLatch

class AdbUiHierarchyDumpTest {
    private val directory = Files.createTempDirectory("sphere-ui-fixture").toFile()
    private val paths = mutableListOf<String>()
    private lateinit var runtime: Runtime
    private lateinit var executor: AdbActionExecutor
    private var xml = """<hierarchy><node text="target" bounds="[10,20][30,40]"/></hierarchy>"""
    private var blockRead = false
    private val readEntered = CountDownLatch(1)
    private val readRelease = CountDownLatch(1)

    @Before fun setup() {
        runtime = mockk()
        val root = mockk<Process>()
        every { root.outputStream } returns ByteArrayOutputStream()
        every { root.isAlive } returns true
        every { runtime.exec("su") } returns root
        every { runtime.exec(any<Array<String>>()) } answers {
            val args = firstArg<Array<String>>()
            val cmd = args[2]
            assertFalse(cmd.contains("killall"))
            assertFalse(cmd.contains("/sdcard"))
            val path = Regex("uiautomator dump '([^']+)'").find(cmd)!!.groupValues[1]
            assertTrue(java.io.File(path).exists())
            assertEquals(directory.canonicalPath, java.io.File(path).parentFile!!.canonicalPath)
            assertEquals("Ownership must span creation, read and unlink", 1, directory.listFiles()!!.size)
            paths.add(path)
            val process = mockk<Process>()
            val bytes = xml.toByteArray(Charsets.UTF_8)
            val partial = object : ByteArrayInputStream(bytes) {
                override fun read(b: ByteArray, off: Int, len: Int): Int {
                    if (blockRead) { readEntered.countDown(); readRelease.await(); return -1 }
                    return super.read(b, off, minOf(len, 7))
                }
                override fun close() { readRelease.countDown(); super.close() }
            }
            every { process.inputStream } returns partial
            every { process.errorStream } returns ByteArrayInputStream(byteArrayOf())
            every { process.outputStream } returns ByteArrayOutputStream()
            every { process.isAlive } returns false
            every { process.exitValue() } returns 0
            process
        }
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        val context = mockk<Context>()
        every { context.cacheDir } returns directory
        executor = AdbActionExecutor(context)
    }

    @After fun cleanup() {
        assertEquals(0, directory.listFiles()!!.size)
        directory.delete()
        unmockkStatic(Runtime::class)
    }

    @Test fun `partial pipe reads produce a complete XPath document with unique private paths`() = runBlocking {
        repeat(2) { assertEquals("20,30", executor.findElement("//node[@text='target']", "xpath", 1_000)) }
        assertEquals(2, paths.toSet().size)
    }

    @Test fun `invalid suffix cannot authorize a match in an earlier node`() = runBlocking {
        xml = xml.removeSuffix("</hierarchy>")
        assertNull(executor.findElement("//node[@text='target']", "xpath", 100))
    }

    @Test fun `oversize dump is incomplete and never parsed as a match`() {
        xml = "<hierarchy text='" + "x".repeat(UiHierarchyXml.MAX_BYTES) + "'/>"
        assertThrows(RootCommandOutcomeUnknownException::class.java) {
            runBlocking { executor.findElement("//node", "xpath", 1_000) }
        }
    }

    @Test fun `concurrent XPath requests cannot overlap dump file ownership`() = runBlocking {
        val first = async(Dispatchers.Default) { executor.findElement("//node", "xpath", 1_000) }
        val second = async(Dispatchers.Default) { executor.findElement("//node", "xpath", 1_000) }
        assertEquals("20,30", first.await())
        assertEquals("20,30", second.await())
        assertEquals(2, paths.toSet().size)
    }

    @Test fun `cancelled dump closes output reader and unlinks its private file`() = runBlocking {
        blockRead = true
        val call = async { executor.findElement("//node", "xpath", 5_000) }
        while (readEntered.count != 0L) delay(5)
        call.cancel()
        try { call.await(); fail("Dump cancellation must propagate") } catch (_: CancellationException) { }
        assertEquals(0, readRelease.count)
        assertEquals(0, directory.listFiles()!!.size)
    }
}
