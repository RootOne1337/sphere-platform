package com.sphereplatform.agent.logging

import timber.log.Timber
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.inject.Inject
import javax.inject.Singleton

/**
 * LogcatCollector — bounded best-effort capture of the logcat output visible to this app UID.
 *
 * Используется:
 *  - командой REQUEST_LOGS / UPLOAD_LOGCAT из CommandHandler
 *  - LogUploadWorker для периодического сбора системных событий
 *
 * `READ_LOGS` is signature/privileged and is not grantable to an ordinary APK.
 * Unfiltered logcat therefore does not promise access to other apps or system
 * crash buffers. This collector retains only a bounded tail to avoid loading an
 * arbitrarily large command output into the agent process.
 */
@Singleton
class LogcatCollector @Inject constructor() {

    companion object {
        internal const val MAX_OUTPUT_BYTES = 2 * 1024 * 1024
        private const val PROCESS_TIMEOUT_SECONDS = 10L

        private val SPHERE_TAGS = listOf(
            "SphereAgent", "SphereWS", "DagRunner", "OtaUpdate",
            "VpnManager", "CmdHandler", "LogUploadW", "UpdateCheckW",
            "ZeroTouch", "NetChange",
        )
    }

    /**
     * Собирает logcat-строки.
     *
     * @param lines  max lines to capture
     * @param tags   if non-null, фильтровать по этим тагам (all others silenced)
     * @return logcat output as String, или сообщение об ошибке
     */
    fun collect(lines: Int = 500, tags: List<String>? = null): String = runCatching {
        val cmd = buildList<String> {
            add("logcat")
            add("-d")                   // dump buffer (non-blocking)
            add("-v")
            add("threadtime")           // timestamp + tid
            add("-t")
            add(lines.coerceIn(1, 5000).toString())
            if (!tags.isNullOrEmpty()) {
                add("*:S")             // silence all by default
                tags.forEach { add("$it:V") }
            }
        }
        val process = ProcessBuilder(cmd)
            .redirectErrorStream(true)
            .start()
        // FIX H5: Лимит на чтение logcat — защита от OOM на слабых эмуляторах.
        // 5000 строк × ~200 байт = ~1MB. Ограничиваем 2MB.
        val output = AtomicReference<ByteArray?>()
        val readFailure = AtomicReference<Exception?>()
        val reader = Thread({
            try {
                output.set(process.inputStream.use { it.readBoundedTail(MAX_OUTPUT_BYTES) })
            } catch (error: Exception) {
                readFailure.set(error)
            }
        }, "sphere-logcat-reader").apply {
            isDaemon = true
            start()
        }
        if (!process.waitFor(PROCESS_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            reader.join(1_000)
            throw IOException("logcat command timed out")
        }
        reader.join(1_000)
        if (reader.isAlive) throw IOException("logcat output reader did not finish")
        readFailure.get()?.let { throw IOException("Could not read logcat output", it) }
        String(output.get() ?: ByteArray(0), Charsets.UTF_8)
    }.getOrElse { e ->
        val msg = "LogcatCollector: failed to read logcat — ${e.message}"
        Timber.w(e, msg)
        msg
    }

    /**
     * Только теги Sphere-агента (самые полезные для отладки приложения).
     */
    fun collectSphereOnly(lines: Int = 1000): String = collect(lines, SPHERE_TAGS)

    /** Requests unfiltered logcat; visibility still depends on Android UID privileges. */
    fun collectSystemFull(lines: Int = 2000): String = collect(lines, tags = null)
}

/** Reads to EOF while retaining only the newest [maxBytes] bytes. */
internal fun InputStream.readBoundedTail(maxBytes: Int): ByteArray {
    require(maxBytes > 0)
    val ring = ByteArray(maxBytes)
    val chunk = ByteArray(minOf(8 * 1024, maxBytes))
    var position = 0
    var total = 0L
    while (true) {
        val read = read(chunk)
        if (read < 0) break
        if (read == 0) continue
        for (index in 0 until read) {
            ring[position] = chunk[index]
            position = (position + 1) % maxBytes
        }
        total += read
    }
    if (total < maxBytes) return ring.copyOf(total.toInt())
    return ByteArray(maxBytes) { index -> ring[(position + index) % maxBytes] }
}
