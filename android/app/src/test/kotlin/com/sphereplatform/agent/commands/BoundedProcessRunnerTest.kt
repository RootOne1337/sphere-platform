package com.sphereplatform.agent.commands

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class BoundedProcessRunnerTest {
    private val runner = BoundedProcessRunner()

    private class HeldStream : InputStream() {
        val closed = CountDownLatch(1)
        val entered = CountDownLatch(1)
        override fun read(): Int { entered.countDown(); closed.await(); return -1 }
        override fun read(bytes: ByteArray, offset: Int, length: Int): Int = read()
        override fun close() { closed.countDown() }
    }

    private class FixtureProcess(
        val out: InputStream = ByteArrayInputStream(byteArrayOf()),
        val err: InputStream = ByteArrayInputStream(byteArrayOf()),
        alive: Boolean = false,
        val code: Int = 0,
    ) : Process() {
        val live = AtomicBoolean(alive)
        val destroyed = AtomicBoolean(false)
        override fun getInputStream() = out
        override fun getErrorStream() = err
        override fun getOutputStream() = ByteArrayOutputStream()
        override fun isAlive() = live.get()
        override fun waitFor(): Int { check(!isAlive); return code }
        override fun waitFor(timeout: Long, unit: TimeUnit) = !isAlive
        override fun exitValue(): Int { check(!isAlive); return code }
        override fun destroy() { destroyed.set(true); live.set(false); out.close(); err.close() }
        override fun destroyForcibly(): Process { destroy(); return this }
    }

    @Test fun `both streams drain beyond retained byte budgets`() = runBlocking {
        val child = PipeProcess(ByteArray(1024 * 1024) { 65 }, ByteArray(1024 * 1024) { 66 })
        val result = runner.run({ child }, 2_000, 1024, 128)
        assertEquals(0, result.exitCode)
        assertArrayEquals(ByteArray(1024) { 65 }, result.stdout.bytes)
        assertArrayEquals(ByteArray(128) { 66 }, result.stderr.bytes)
        assertTrue(result.stdout.truncated && result.stderr.truncated)
        assertFalse(child.isAlive)
    }

    @Test fun `partial reads are accumulated until EOF`() = runBlocking {
        val bytes = "дерево-é-界".toByteArray(Charsets.UTF_8)
        val stream = object : ByteArrayInputStream(bytes) {
            override fun read(b: ByteArray, off: Int, len: Int) = super.read(b, off, minOf(len, 1))
        }
        val result = runner.run({ FixtureProcess(out = stream) }, 1_000, 1024, 128)
        assertArrayEquals(bytes, result.stdout.bytes)
        assertFalse(result.stdout.truncated)
    }

    @Test fun `nonzero exit preserves exit code without logging payload`() = runBlocking {
        val result = runner.run({ FixtureProcess(code = 17) }, 1_000, 10, 10)
        assertEquals(17, result.exitCode)
    }

    @Test fun `deadline also covers pipes held open after process exit`() {
        val pipe = HeldStream()
        val child = FixtureProcess(out = pipe)
        val error = assertThrows(ProcessOutputIncompleteException::class.java) {
            runBlocking { runner.run({ child }, 80, 10, 10) }
        }
        assertEquals("execution_read_timeout", error.reason)
        assertEquals(0, pipe.closed.count)
    }

    @Test fun `deadline terminates owned process and closes streams`() {
        val child = FixtureProcess(out = HeldStream(), err = HeldStream(), alive = true)
        assertThrows(ProcessOutputIncompleteException::class.java) {
            runBlocking { runner.run({ child }, 80, 10, 10) }
        }
        assertTrue(child.destroyed.get())
        assertFalse(child.isAlive)
    }

    @Test fun `cancellation keeps its meaning and cleans up active readers`() = runBlocking {
        val pipe = HeldStream()
        val child = FixtureProcess(out = pipe, alive = true)
        val call = async { runner.run({ child }, 5_000, 10, 10) }
        while (pipe.entered.count != 0L) delay(5)
        call.cancel()
        try { call.await(); fail("Cancellation must propagate") } catch (_: CancellationException) { }
        assertTrue(child.destroyed.get())
        assertEquals(0, pipe.closed.count)
    }

    @Test fun `read failure cannot return an empty successful output`() {
        val broken = object : InputStream() { override fun read(): Int = throw java.io.IOException("sensitive") }
        val error = assertThrows(ProcessOutputIncompleteException::class.java) {
            runBlocking { runner.run({ FixtureProcess(out = broken) }, 1_000, 10, 10) }
        }
        assertEquals("output_read_failed", error.reason)
        assertFalse(error.toString().contains("sensitive"))
    }
}
