package com.sphereplatform.agent.logging

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
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
        private const val MAX_READ_BYTES = 256 * 1024
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

    /** UTF-8 byte budget across all files, capped at 256 KiB; newest content last. */
    @Synchronized
    fun readRecentLogs(maxBytes: Int = 64 * 1024): String {
        val files = logFiles().sortedBy { it.lastModified() }
        val chunks = mutableListOf<String>()
        var remaining = maxBytes.coerceIn(0, MAX_READ_BYTES)
        for (file in files.reversed()) {
            if (remaining <= 0) break
            try {
                // File lengths and seek offsets are bytes. Reader.skip counts
                // characters and can skip beyond EOF on Cyrillic/emoji logs.
                // The same monitor as writeEntry prevents partial UTF-8 appends
                // and internal rotation while taking this bounded snapshot.
                RandomAccessFile(file, "r").use { input ->
                    val length = input.length()
                    val count = minOf(length, remaining.toLong()).toInt()
                    if (count > 0) {
                        val bytes = ByteArray(count)
                        input.seek(length - count)
                        input.readFully(bytes)
                        // A byte-tail may start inside a code point; a previous
                        // process crash may leave an incomplete final code point.
                        // Drop incomplete/malformed sequences without expanding
                        // the byte budget through replacement characters.
                        val decoder = Charsets.UTF_8.newDecoder()
                            .onMalformedInput(CodingErrorAction.IGNORE)
                            .onUnmappableCharacter(CodingErrorAction.IGNORE)
                        chunks.add(decoder.decode(ByteBuffer.wrap(bytes)).toString())
                        remaining -= count
                    }
                }
            } catch (_: IOException) {
                // A missing/unreadable file must not hide other retained logs.
            }
        }
        return chunks.asReversed().joinToString("")
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
