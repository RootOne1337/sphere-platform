package com.sphereplatform.agent.commands

import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException
import kotlin.coroutines.EmptyCoroutineContext

class RootCommandAcknowledgementTest {
    private fun process(bytes: ByteArray, alive: Boolean = true): Process {
        val input = object : ByteArrayInputStream(bytes) {
            override fun available(): Int = minOf(super.available(), 3)
        }
        return mockk<Process>().also {
            every { it.inputStream } returns input
            every { it.errorStream } returns ByteArrayInputStream(byteArrayOf())
            every { it.isAlive } returns alive
        }
    }

    @Test fun `partial reads ignore stale markers and return only the owned exit status`() {
        val raw = "private prior output\nsphere_clear_old:0\n" + "x".repeat(200) + "\nowned:7\n"
        assertEquals(7, RootCommandAcknowledgement.await(process(raw.toByteArray()), "owned", EmptyCoroutineContext))
    }

    @Test fun `malformed owned result is never a successful empty result`() {
        assertThrows(IOException::class.java) {
            RootCommandAcknowledgement.await(process("\nowned:bad\n".toByteArray()), "owned", EmptyCoroutineContext)
        }
    }

    @Test fun `process death and missing marker are unknown instead of successful`() {
        assertThrows(IOException::class.java) {
            RootCommandAcknowledgement.await(process(byteArrayOf(), false), "owned", EmptyCoroutineContext)
        }
        assertThrows(IOException::class.java) {
            RootCommandAcknowledgement.await(process(byteArrayOf()), "owned", EmptyCoroutineContext, 1)
        }
    }

    @Test fun `cancellation prevents consuming an already available success marker`() {
        val owner = Job().apply { cancel() }
        assertThrows(CancellationException::class.java) {
            RootCommandAcknowledgement.await(process("\nowned:0\n".toByteArray()), "owned", owner)
        }
    }

    @Test fun `unbounded prior process output cannot be retained or accepted`() {
        val owned = mockk<Process>()
        every { owned.inputStream } returns ByteArrayInputStream(ByteArray(256 * 1024 + 4096) { 120 })
        every { owned.errorStream } returns ByteArrayInputStream(byteArrayOf())
        every { owned.isAlive } returns true
        assertThrows(IOException::class.java) {
            RootCommandAcknowledgement.await(owned, "owned", EmptyCoroutineContext)
        }
    }
}
