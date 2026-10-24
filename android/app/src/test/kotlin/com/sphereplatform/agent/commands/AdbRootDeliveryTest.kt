package com.sphereplatform.agent.commands

import android.content.Context
import com.sphereplatform.agent.lua.LuaEngine
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.unmockkStatic
import io.mockk.verify
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.IOException

/** Process-pipe failure at a boundary where the shell may have consumed input. */
class AdbRootDeliveryTest {
    private val firstInput = object : ByteArrayOutputStream() {
        override fun flush() {
            // All bytes, including newline, have already reached the fake pipe.
            throw IOException("audit: lost pipe flush confirmation")
        }
    }
    private val nextInput = ByteArrayOutputStream()
    private lateinit var runtime: Runtime
    private lateinit var first: Process
    private lateinit var executor: AdbActionExecutor

    @Before
    fun setUp() {
        runtime = mockk()
        first = mockk()
        val next = mockk<Process>()
        every { first.outputStream } returns firstInput
        every { first.isAlive } returns true
        every { first.destroyForcibly() } returns first
        every { next.outputStream } returns nextInput
        every { next.isAlive } returns true
        every { runtime.exec("su") } returnsMany listOf(first, next)
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        executor = AdbActionExecutor(mockk<Context>())
    }

    @After
    fun tearDown() {
        unmockkStatic(Runtime::class)
    }

    @Test
    fun `flush failure must not replay a possibly delivered tap`() {
        val failure = runCatching { executor.tapRaw(10, 20) }.exceptionOrNull()
        assertEquals("input tap 10 20\n", firstInput.toString("UTF-8"))
        assertEquals("Uncertain command must not be replayed into a fresh pipe", "", nextInput.toString("UTF-8"))
        assertTrue(failure is IOException)
        assertTrue(failure?.message.orEmpty().contains("unknown", ignoreCase = true))
        verify(exactly = 1) { runtime.exec("su") }
    }

    @Test
    fun `next explicit command opens a fresh session without replaying the failed command`() {
        assertThrows(IOException::class.java) { executor.tapRaw(10, 20) }
        // A dead/dying Process may still report isAlive. A broken pipe must be
        // invalidated independently of that OS observation.
        executor.keyEvent(4)
        assertEquals("input tap 10 20\n", firstInput.toString("UTF-8"))
        assertEquals("input keyevent 4\n", nextInput.toString("UTF-8"))
        verify(exactly = 2) { runtime.exec("su") }
        verify(exactly = 1) { first.destroyForcibly() }
    }

    private fun verifyDagStops(action: String) {
        val runner = DagRunner(LuaEngine(executor), executor, mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true))
        val dag = Json.parseToJsonElement("""{
            "entry_node":"input", "nodes":[
                {"id":"input", "retry":3, "on_failure":"fallback", "action":$action},
                {"id":"fallback", "action":{"type":"key_event", "keycode":4}}
            ]
        }""").jsonObject
        assertThrows(IOException::class.java) { runBlocking { runner.execute("audit-unknown-root", dag) } }
        assertEquals("input keyevent 66\n", firstInput.toString("UTF-8"))
        assertEquals("", nextInput.toString("UTF-8"))
        verify(exactly = 1) { runtime.exec("su") }
    }

    @Test
    fun `unknown root outcome bypasses node retry and failure routing`() {
        verifyDagStops("""{"type":"key_event", "keycode":66}""")
    }

    @Test
    fun `loop cannot swallow unknown root outcome and continue input`() {
        verifyDagStops("""{"type":"loop", "count":3, "body":[
            {"id":"nested", "action":{"type":"key_event", "keycode":66}}
        ]}""")
    }

    @Test
    fun `Lua binding failure must not be retried by the DAG`() {
        verifyDagStops("""{"type":"lua", "code":"key_event(66); return true"}""")
    }
}
