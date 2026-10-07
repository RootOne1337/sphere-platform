package com.sphereplatform.agent.commands

import kotlinx.coroutines.ensureActive
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.CoroutineContext

/** Read a unique shell marker without retaining previous command output or creating reader threads. */
internal object RootCommandAcknowledgement {
    fun await(process: Process, marker: String, context: CoroutineContext, timeoutMs: Long = 5_000): Int {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs)
        val stdout = process.inputStream
        val stderr = process.errorStream
        val chunk = ByteArray(4096)
        val tail = StringBuilder()
        var drained = 0
        val prefix = "\n$marker:"
        while (true) {
            context.ensureActive()
            if (System.nanoTime() >= deadline) throw IOException("input_clear_ack_timeout")
            var available = stdout.available()
            if (available > 0) {
                val count = stdout.read(chunk, 0, minOf(available, chunk.size))
                if (count < 0) throw IOException("input_clear_ack_eof")
                drained += count
                if (drained > 256 * 1024) throw IOException("input_clear_ack_output_budget")
                tail.append(String(chunk, 0, count, Charsets.US_ASCII))
                val start = tail.indexOf(prefix)
                if (start >= 0) {
                    val end = tail.indexOf("\n", start + prefix.length)
                    if (end >= 0) {
                        return tail.substring(start + prefix.length, end).removeSuffix("\r").toIntOrNull()
                            ?: throw IOException("input_clear_ack_malformed")
                    }
                }
                if (tail.length > 128) tail.delete(0, tail.length - 128)
            }
            available = stderr.available()
            if (available > 0) {
                val count = stderr.read(chunk, 0, minOf(available, chunk.size))
                if (count > 0) drained += count
                if (drained > 256 * 1024) throw IOException("input_clear_ack_output_budget")
            }
            if (!process.isAlive && stdout.available() == 0) throw IOException("input_clear_ack_process_exited")
            // Runs under the root ownership lock on Dispatchers.IO, not the UI/event loop.
            Thread.sleep(10)
        }
    }
}
