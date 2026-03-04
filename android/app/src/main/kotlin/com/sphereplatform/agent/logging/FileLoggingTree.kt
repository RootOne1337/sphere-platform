package com.sphereplatform.agent.logging

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.LinkedBlockingQueue
import javax.inject.Inject
import javax.inject.Singleton

/**
 * FileLoggingTree — персистентный Timber-tree с ротацией файлов.
 *
 * Архитектура:
 *  - Non-blocking: записи помещаются в LinkedBlockingQueue и пишутся daemon-потоком
 *  - Ротация: MAX_FILE_SIZE(2 MB) → переключается на следующий файл, хранит MAX_FILE_COUNT(5)
 *  - Формат: "2026-02-23T10:15:30.123 D/Tag: message\n"
 *  - Доступ: readRecentLogs(maxBytes) для LogUploadWorker
 *
 * Hilt: @Singleton, требует @ApplicationContext
 */
@Singleton
class FileLoggingTree @Inject constructor(
    @ApplicationContext private val context: Context,
) : Timber.Tree() {

    companion object {
        private const val MAX_FILE_SIZE = 2 * 1024 * 1024L   // 2 MB
        private const val MAX_FILE_COUNT = 5
        private const val MAX_QUEUE_SIZE = 4096
        private const val LOG_DIR = "sphere_logs"
        private const val LOG_PREFIX = "sphere_"
        private const val LOG_EXT = ".log"
    }

    private val logDir: File = File(context.filesDir, LOG_DIR).also { it.mkdirs() }
    /**
     * FIX E1: ThreadLocal вместо shared SimpleDateFormat.
     * SimpleDateFormat НЕ потокобезопасен — format() мутирует внутренний Calendar.
     * Timber.log() вызывается из любого потока (WS, coroutine, MediaCodec callback),
     * конкурентный format() → ArrayIndexOutOfBoundsException или garbled timestamps.
     */
    private val dateFormat = ThreadLocal.withInitial {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US)
    }
    private val queue = LinkedBlockingQueue<String>(MAX_QUEUE_SIZE)

    @Volatile private var currentFile: File = resolveCurrentFile()

    private val writerThread = Thread({
        while (!Thread.currentThread().isInterrupted) {
            try {
                val entry = queue.take()
                writeEntry(entry)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            } catch (e: Exception) {
                // If writing fails (disk full, etc.) just drop the entry silently
                System.err.println("FileLoggingTree write error: ${e.message}")
            }
        }
    }, "sphere-log-writer").also {
        it.isDaemon = true
        it.start()
    }

    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        val level = priorityChar(priority)
        val ts = dateFormat.get()!!.format(Date())
        val tagPart = if (tag != null) "$tag" else "?"
        val entry = buildString {
            append("$ts $level/$tagPart: $message")
            if (t != null) append("\n${t.stackTraceToString()}")
            append('\n')
        }
        // Offer (non-blocking): drop if queue is full to avoid blocking app
        queue.offer(entry)
    }

    /** Read up to [maxBytes] of the most recent log content (newest data last). */
    fun readRecentLogs(maxBytes: Int = 64 * 1024): String {
        val files = logFiles().sortedBy { it.lastModified() }
        val result = StringBuilder()
        var remaining = maxBytes
        for (file in files.reversed()) {
            if (remaining <= 0) break
            try {
                // FIX H5: Читаем только нужную часть файла, а не весь целиком.
                // Файлы до 2MB — readText() грузит всё в память. На 1GB эмуляторе
                // при 5 файлах × 2MB = 10MB UTF-16 String = 20MB heap pressure.
                val fileLen = file.length().toInt()
                if (fileLen <= remaining) {
                    val content = file.readText(Charsets.UTF_8)
                    result.insert(0, content)
                    remaining -= content.length
                } else {
                    // Читаем только хвост файла (самые свежие записи)
                    file.reader(Charsets.UTF_8).use { reader ->
                        val skip = (fileLen - remaining).toLong().coerceAtLeast(0)
                        reader.skip(skip)
                        val tail = CharArray(remaining)
                        val read = reader.read(tail)
                        if (read > 0) result.insert(0, String(tail, 0, read))
                    }
                    remaining = 0
                }
            } catch (_: Exception) {}
        }
        return result.toString()
    }

    /** All log files, sorted oldest-first. */
    fun getLogFiles(): List<File> = logFiles().sortedBy { it.lastModified() }

    // ── Private helpers ──────────────────────────────────────────────────────

    @Synchronized
    private fun writeEntry(entry: String) {
        if (currentFile.length() >= MAX_FILE_SIZE) {
            rotate()
        }
        currentFile.appendText(entry, Charsets.UTF_8)
    }

    private fun rotate() {
        currentFile = newLogFile()
        pruneOldFiles()
    }

    private fun pruneOldFiles() {
        val files = logFiles().sortedBy { it.lastModified() }
        if (files.size > MAX_FILE_COUNT) {
            files.take(files.size - MAX_FILE_COUNT).forEach { it.delete() }
        }
    }

    private fun logFiles(): List<File> =
        logDir.listFiles { f -> f.name.startsWith(LOG_PREFIX) && f.name.endsWith(LOG_EXT) }
            ?.toList() ?: emptyList()

    private fun resolveCurrentFile(): File {
        val existing = logFiles()
            .filter { it.length() < MAX_FILE_SIZE }
            .maxByOrNull { it.lastModified() }
        return existing ?: newLogFile()
    }

    private fun newLogFile(): File {
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        return File(logDir, "$LOG_PREFIX${ts}$LOG_EXT")
    }

    private fun priorityChar(priority: Int): Char = when (priority) {
        android.util.Log.VERBOSE -> 'V'
        android.util.Log.DEBUG   -> 'D'
        android.util.Log.INFO    -> 'I'
        android.util.Log.WARN    -> 'W'
        android.util.Log.ERROR   -> 'E'
        android.util.Log.ASSERT  -> 'A'
        else                     -> '?'
    }
}
