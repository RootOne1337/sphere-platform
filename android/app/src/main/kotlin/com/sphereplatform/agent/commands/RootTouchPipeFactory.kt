package com.sphereplatform.agent.commands

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

internal class TouchPipeCleanupUnknownException : IOException("touch_cleanup_unknown")

/** Lazy factory: construction never asks for root, creates a file, or opens a process. */
internal class RootTouchPipeFactory(private val context: Context) : TouchPipeFactory {
    override suspend fun open(binding: TouchBinding): TouchPipe = withContext(Dispatchers.IO) {
        coroutineContext.ensureActive()
        val apk = context.applicationInfo.sourceDir
        require(apk.startsWith("/") && apk.endsWith(".apk") && apk.length <= 4096 && apk.none { it == '\r' || it == '\n' || it == '\u0000' })
        val quotedApk = "'" + apk.replace("'", "'\\''") + "'"
        val command = "CLASSPATH=$quotedApk exec /system/bin/app_process /system/bin " +
            "com.sphereplatform.agent.commands.RootTouchBridge touch-v1 ${binding.width} ${binding.height} ${binding.rotation}"
        // No root command shares the existing discrete-input stdout or ownership lock.
        val process = ProcessBuilder("su", "-c", command).start()
        val pipe = try { ProcessTouchPipe(process) } catch (failure: Exception) {
            runCatching { process.outputStream.close() }
            runCatching { process.destroyForcibly() }
            throw TouchPipeCleanupUnknownException()
        }
        try {
            val ready = pipe.awaitAck(5_000)
            if (ready.sequence != 0 || ready.status != 0) throw IOException("touch_ready_invalid")
            pipe
        } catch (failure: Exception) {
            val confirmed = withContext(NonCancellable) { pipe.closeAndConfirm() }
            if (!confirmed) throw TouchPipeCleanupUnknownException()
            throw failure
        }
    }
}

internal class ProcessTouchPipe(private val process: Process) : TouchPipe {
    private var closed = false
    private var lastSequence = 0
    private var stderrBytes = 0
    private val stdout = process.inputStream
    private val stderr = process.errorStream
    private val stdin = process.outputStream

    override suspend fun send(sample: TouchSample): RootTouchWire.Ack {
        check(!closed)
        if (sample.sequence <= lastSequence) throw IOException("touch_sequence_invalid")
        RootTouchWire.write(stdin, RootTouchWire.Packet(sample.sequence, sample.gesture, sample.action, sample.x, sample.y))
        lastSequence = sample.sequence
        val ack = awaitAck(500)
        if (ack.sequence != sample.sequence || ack.status == 0) throw IOException("touch_ack_mismatch")
        val expected = when (sample.action) { RootTouchSession.HEARTBEAT -> 2; RootTouchSession.CANCEL -> 3; else -> 1 }
        if (ack.status in 1..3 && ack.status != expected) throw IOException("touch_ack_action_mismatch")
        // A false or unknown reply is never retried. The supervisor retires the owner.
        return ack
    }

    internal suspend fun awaitAck(timeoutMs: Long): RootTouchWire.Ack {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs)
        val line = ByteArrayOutputStream(RootTouchWire.ACK_LINE_BYTES + 1)
        while (true) {
            coroutineContext.ensureActive()
            if (System.nanoTime() >= deadline) throw IOException("touch_ack_timeout")
            val available = stdout.available()
            if (available > 0) {
                // One byte per bounded ACK prevents accidentally consuming the next message.
                val value = stdout.read()
                if (value < 0) throw IOException("touch_ack_eof")
                if (line.size() >= RootTouchWire.ACK_LINE_BYTES + 1) throw IOException("touch_ack_budget")
                line.write(value)
                if (value == '\n'.code) return RootTouchWire.readAck(ByteArrayInputStream(line.toByteArray()))
            } else {
                drainStderr()
                if (!process.isAlive) throw IOException("touch_process_exited")
                delay(2)
            }
        }
    }

    private fun drainStderr() {
        val available = stderr.available()
        if (available <= 0) return
        val chunk = ByteArray(minOf(available, 1024))
        val count = stderr.read(chunk)
        if (count > 0) stderrBytes += count
        // Discard private/platform errors; a flooding helper is unhealthy, never a growing log.
        if (stderrBytes > 4096) throw IOException("touch_stderr_budget")
    }

    override suspend fun closeAndConfirm(): Boolean = withContext(NonCancellable + Dispatchers.IO) {
        if (closed) return@withContext false
        closed = true
        runCatching { stdin.close() }
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
        // EOF asks the helper to cancel before exiting. Force-kill is cleanup, not release confirmation.
        var drainValid = true
        var outputBytes = 0
        while (process.isAlive && System.nanoTime() < deadline) {
            runCatching { drainStderr() }.onFailure { drainValid = false }
            runCatching {
                val count = stdout.available()
                if (count > 0) {
                    outputBytes += stdout.read(ByteArray(minOf(count, 1024)))
                    if (outputBytes > 4096) drainValid = false
                }
            }.onFailure { drainValid = false }
            delay(10)
        }
        val confirmed = drainValid && !process.isAlive && runCatching { process.exitValue() == 0 }.getOrDefault(false)
        if (process.isAlive) runCatching { process.destroyForcibly() }
        runCatching { stdout.close() }
        runCatching { stderr.close() }
        if (process.isAlive) runCatching { process.waitFor(250, TimeUnit.MILLISECONDS) }
        confirmed
    }
}
