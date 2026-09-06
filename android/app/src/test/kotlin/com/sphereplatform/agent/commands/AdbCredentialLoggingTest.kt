package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.unmockkStatic
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import timber.log.Timber
import java.io.ByteArrayOutputStream
import java.util.concurrent.CopyOnWriteArrayList

/** Real executor/Timber calls; no su, ADB, emulator or external process is run. */
class AdbCredentialLoggingTest {
    private val messages = CopyOnWriteArrayList<String>()
    private val rootInput = ByteArrayOutputStream()
    private val tree = object : Timber.Tree() {
        override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
            messages.add(message)
            if (t != null) messages.add(t.stackTraceToString())
        }
    }
    private lateinit var executor: AdbActionExecutor

    @Before
    fun setUp() {
        val runtime = mockk<Runtime>()
        val process = mockk<Process>()
        every { process.outputStream } returns rootInput
        every { process.isAlive } returns true
        every { runtime.exec("su") } returns process
        mockkStatic(Runtime::class)
        every { Runtime.getRuntime() } returns runtime
        Timber.plant(tree)
        executor = AdbActionExecutor(mockk<Context>())
    }

    @After
    fun tearDown() {
        Timber.uproot(tree)
        unmockkStatic(Runtime::class)
    }

    private fun verifySensitiveInput(text: String) = runBlocking {
        executor.typeText(text)
        val escaped = text.replace(" ", "%s").replace("'", "'\\''")
        assertTrue("The original text input command must still be delivered",
            rootInput.toString("UTF-8").contains("input text '$escaped'\n"))
        assertFalse("Raw input must not reach any Timber sink", messages.any { it.contains(text) })
        assertFalse("Shell-encoded input is still a credential", messages.any { it.contains(escaped) })
    }

    @Test
    fun `ordinary password is sent to root input but never logged`() {
        verifySensitiveInput("audit-password-8614")
    }

    @Test
    fun `quotes and spaces do not leak an encoded password`() {
        verifySensitiveInput("audit private'credential")
    }
}
