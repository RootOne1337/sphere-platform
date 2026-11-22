package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.unmockkStatic
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** The child cannot exit until both finite OS-like pipes have been drained. */
internal class PipeProcess(stdout: ByteArray, stderr: ByteArray) : Process() {
    private val out = PipedInputStream(1024)
    private val err = PipedInputStream(1024)
    private val outWriter = PipedOutputStream(out)
    private val errWriter = PipedOutputStream(err)
    private val finished = CountDownLatch(2)
    private val input = ByteArrayOutputStream()
    private val writers = listOf(outWriter to stdout, errWriter to stderr).map { (writer, bytes) ->
        Thread({
            try {
                writer.use { it.write(bytes) }
            } catch (_: java.io.IOException) {
                // Cleanup may close a pipe while the child is still writing.
            } finally {
                finished.countDown()
            }
        }, "fixture-child-pipe").apply { isDaemon = true; start() }
    }

    override fun getInputStream() = out
    override fun getErrorStream() = err
    override fun getOutputStream() = input
    override fun isAlive() = finished.count > 0
    override fun waitFor(): Int { finished.await(); return 0 }
    override fun waitFor(timeout: Long, unit: TimeUnit) = finished.await(timeout, unit)
    override fun exitValue(): Int {
        if (isAlive) throw IllegalThreadStateException()
        return 0
    }
    override fun destroy() {
        outWriter.close(); errWriter.close()
        out.close(); err.close()
        writers.forEach { it.interrupt() }
    }
    override fun destroyForcibly(): Process { destroy(); return this }
}

class AdbCommandOutputTest {
    private lateinit var runtime: Runtime
    private lateinit var executor: AdbActionExecutor
    private val rootInput = ByteArrayOutputStream()
    private val children = mutableListOf<Process>()

    @Before fun setup() {
        runtime = mockk()
        val root = mockk<Process>()
        every { root.outputStream } returns rootInput
        every { root.isAlive } returns true
        every { runtime.exec("su") } returns root
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        executor = AdbActionExecutor(mockk<Context>())
    }

    @After fun cleanup() {
        children.forEach { it.destroyForcibly() }
        unmockkStatic(Runtime::class)
    }

    private fun child(stdout: String, stderr: String) {
        val process = PipeProcess(stdout.toByteArray(), stderr.toByteArray())
        children.add(process)
        every { runtime.exec(arrayOf("su", "-c", "fixture")) } returns process
    }

    @Test fun `shell drains stdout before waiting for child exit`() = runBlocking {
        val expected = "valid-output\n".repeat(8192)
        child(expected, "")
        assertEquals(expected, executor.shell("fixture"))
    }

    @Test fun `successful shell also drains large stderr without deadlock`() = runBlocking {
        child("ok", "diagnostic\n".repeat(16384))
        assertEquals("ok", executor.shell("fixture"))
    }

    @Test fun `oversize stdout is an explicit incomplete result instead of silent success`() {
        child("x".repeat(300 * 1024), "")
        assertThrows(RootCommandOutcomeUnknownException::class.java) {
            runBlocking { executor.shell("fixture") }
        }
    }

    @Test fun `DAG cannot ignore an uncertain shell output and continue input`() {
        child("x".repeat(300 * 1024), "")
        val runner = DagRunner(mockk(relaxed = true), executor, mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true))
        val dag = Json.parseToJsonElement("""{
            "entry_node":"shell", "nodes":[
                {"id":"shell", "retry":3, "on_success":"tap", "on_failure":"tap",
                 "action":{"type":"shell","command":"fixture","fail_on_error":false}},
                {"id":"tap", "action":{"type":"key_event","keycode":66}}
            ]
        }""").jsonObject
        assertThrows(RootCommandOutcomeUnknownException::class.java) {
            runBlocking { runner.execute("audit-shell-output", dag) }
        }
        assertEquals("", rootInput.toString("UTF-8"))
        io.mockk.verify(exactly = 1) { runtime.exec(arrayOf("su", "-c", "fixture")) }
    }
}
