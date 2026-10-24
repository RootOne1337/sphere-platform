package com.sphereplatform.agent.commands

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.coroutineContext

internal class ProcessOutputIncompleteException(val reason: String) : IOException(reason)

/** One command, two concurrent drains, bounded retained bytes and one execution/read deadline. */
internal class BoundedProcessRunner {
    data class Output(val bytes: ByteArray, val truncated: Boolean)
    data class Result(val exitCode: Int, val stdout: Output, val stderr: Output)
    private val ownership = Mutex()

    suspend fun run(
        start: () -> Process,
        timeoutMs: Long,
        stdoutLimit: Int,
        stderrLimit: Int,
    ): Result = ownership.withLock {
        require(timeoutMs in 1..30_000 && stdoutLimit in 1..1024 * 1024 && stderrLimit in 1..1024 * 1024)
        withContext(Dispatchers.IO) {
            coroutineContext.ensureActive()
            val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs)
            val process = start() // Failure to spawn is distinct from an uncertain result after spawn.
            val readers = mutableListOf<Thread>()
            val failure = AtomicReference<Exception?>()
            val out = AtomicReference<Output?>()
            val err = AtomicReference<Output?>()
            var outcome: Exception? = null

            fun drain(stream: InputStream, limit: Int, result: AtomicReference<Output?>, name: String) {
                val thread = Thread({
                    try {
                        result.set(stream.use { readPrefix(it, limit) })
                    } catch (error: Exception) {
                        failure.compareAndSet(null, error)
                    }
                }, name).apply { isDaemon = true }
                readers.add(thread)
                thread.start()
            }

            try {
                process.outputStream.close() // This API has no interactive stdin.
                drain(process.inputStream, stdoutLimit, out, "sphere-command-stdout")
                drain(process.errorStream, stderrLimit, err, "sphere-command-stderr")
                while (process.isAlive || readers.any { it.isAlive }) {
                    coroutineContext.ensureActive()
                    if (failure.get() != null) throw ProcessOutputIncompleteException("output_read_failed")
                    if (System.nanoTime() >= deadline) throw ProcessOutputIncompleteException("execution_read_timeout")
                    delay(10)
                }
                if (failure.get() != null) throw ProcessOutputIncompleteException("output_read_failed")
                Result(process.exitValue(), out.get() ?: error("stdout reader missing"),
                    err.get() ?: error("stderr reader missing"))
            } catch (error: CancellationException) {
                outcome = error
                throw error
            } catch (error: Exception) {
                val incomplete = error as? ProcessOutputIncompleteException
                    ?: ProcessOutputIncompleteException("execution_failed_after_spawn")
                outcome = incomplete
                throw incomplete
            } finally {
                // Cancellation must not leave readers or the directly owned process behind.
                // A root shell's descendants need separate device-level lifecycle acceptance.
                withContext(NonCancellable + Dispatchers.IO) {
                    if (process.isAlive) runCatching { process.destroyForcibly() }
                    runCatching { process.outputStream.close() }
                    runCatching { process.inputStream.close() }
                    runCatching { process.errorStream.close() }
                    readers.forEach { it.interrupt() }
                    readers.forEach { it.join(250) }
                    if (process.isAlive) runCatching { process.waitFor(250, TimeUnit.MILLISECONDS) }
                    if (readers.any { it.isAlive } || process.isAlive) {
                        val incomplete = ProcessOutputIncompleteException("owned_process_cleanup_incomplete")
                        if (outcome != null) outcome.addSuppressed(incomplete) else throw incomplete
                    }
                }
            }
        }
    }

    private fun readPrefix(stream: InputStream, limit: Int): Output {
        val retained = ByteArray(limit)
        val chunk = ByteArray(8 * 1024)
        var size = 0
        var truncated = false
        while (true) {
            val count = stream.read(chunk)
            if (count < 0) break
            if (count == 0) continue
            val copy = minOf(count, limit - size)
            if (copy > 0) chunk.copyInto(retained, size, 0, copy)
            size += copy
            truncated = truncated || count > copy
            // Keep draining excess bytes: stopping here would fill the child's pipe.
        }
        return Output(retained.copyOf(size), truncated)
    }
}
