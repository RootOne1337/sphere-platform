package com.sphereplatform.agent.logging

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.io.PrintWriter
import java.io.RandomAccessFile
import java.io.Writer
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
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
        // Count AND bytes are bounded: at most 4 MiB of encoded queued payload.
        private const val MAX_QUEUE_SIZE = 256
        private const val MAX_ENTRY_BYTES = 16 * 1024
        private const val TRUNCATED_ENTRY = "\n[log entry truncated]\n"
        private const val MAX_READ_BYTES = 256 * 1024
        private const val MAX_WS_LIFECYCLE_FILE_BYTES = 64 * 1024
        private const val RETAIN_WS_LIFECYCLE_FILE_BYTES = 32 * 1024
        private const val LOG_DIR = "sphere_logs"
        private const val LOG_PREFIX = "sphere_"
        private const val LOG_EXT = ".log"
        private const val WS_LIFECYCLE_FILE = "ws_lifecycle.log"
    }

    private val logDir: File = File(context.filesDir, LOG_DIR).also { it.mkdirs() }
    // Keep sparse transport incident records outside the noisy rolling log tail.
    // This sidecar is bounded and is intentionally excluded from logFiles().
    private val wsLifecycleFile = File(logDir, WS_LIFECYCLE_FILE)
    private val wsLifecycleLock = Any()
    /**
     * FIX E1: ThreadLocal вместо shared SimpleDateFormat.
     * SimpleDateFormat НЕ потокобезопасен — format() мутирует внутренний Calendar.
     * Timber.log() вызывается из любого потока (WS, coroutine, MediaCodec callback),
     * конкурентный format() → ArrayIndexOutOfBoundsException или garbled timestamps.
     */
    private val dateFormat = ThreadLocal.withInitial {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US)
    }
    private val queue = LinkedBlockingQueue<ByteArray>(MAX_QUEUE_SIZE)
    @Volatile private var droppedEntries = 0L
    private var fileSequence = 0L
    private val fileOrder = compareBy<File> { it.lastModified() }.thenBy { it.name }

    @Volatile private var currentFile: File = runCatching { resolveCurrentFile() }.getOrElse {
        // Logging must not prevent app startup on a full/unwritable filesystem.
        System.err.println("FileLoggingTree startup error: ${it.javaClass.simpleName}")
        File(logDir, "$LOG_PREFIX${UUID.randomUUID()}$LOG_EXT")
    }

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
        val tagPart = tag ?: "?"
        val trace = t?.let {
            BoundedLogWriter(MAX_ENTRY_BYTES).also { writer ->
                PrintWriter(writer).use { printer -> it.printStackTrace(printer) }
            }
        }
        val entry = buildString {
            append("$ts $level/${tagPart.take(512)}: ")
            append(message.take(MAX_ENTRY_BYTES))
            if (trace != null) append('\n').append(trace.text)
            append('\n')
        }
        val encoded = boundedEntry(entry, message.length > MAX_ENTRY_BYTES ||
            tagPart.length > 512 || trace?.truncated == true)
        // Never wait for disk I/O. Prefer the newest diagnostic evidence on
        // overflow; serializing producers prevents their eviction/offers racing.
        synchronized(queue) {
            if (!queue.offer(encoded)) {
                if (queue.poll() != null) droppedEntries++
                queue.offer(encoded)
            }
        }
    }

    /** Overflow is observable; a saturated logger is not a lossless event journal. */
    fun getDroppedEntryCount(): Long = droppedEntries

    /** UTF-8 byte budget across all files, capped at 256 KiB; newest content last. */
    @Synchronized
    fun readRecentLogs(maxBytes: Int = 64 * 1024): String {
        val files = logFiles().sortedWith(fileOrder)
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

    /**
     * Return the bounded, newest WebSocket lifecycle records independent of
     * routine log volume. The sidecar is capped at 64 KiB and is read only by
     * diagnostics upload; callers must not expose it without normal log ACLs.
     */
    fun readRecentWebSocketLifecycleLogs(maxBytes: Int = 32 * 1024): String {
        val budget = maxBytes.coerceIn(0, MAX_WS_LIFECYCLE_FILE_BYTES)
        if (budget == 0) return ""
        return synchronized(wsLifecycleLock) {
            runCatching {
                if (!wsLifecycleFile.isFile) return@synchronized ""
                val bytes = wsLifecycleFile.readBytes()
                var start = (bytes.size - budget).coerceAtLeast(0)
                if (start > 0) {
                    val nextLine = indexOfLineFeed(bytes, start)
                    if (nextLine < 0) return@synchronized ""
                    start = nextLine + 1
                }
                val decoder = Charsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.IGNORE)
                    .onUnmappableCharacter(CodingErrorAction.IGNORE)
                decoder.decode(ByteBuffer.wrap(bytes, start, bytes.size - start)).toString()
            }.getOrDefault("")
        }
    }

    /** All log files, sorted oldest-first. */
    fun getLogFiles(): List<File> = logFiles().sortedWith(fileOrder)

    // ── Private helpers ──────────────────────────────────────────────────────

    @Synchronized
    private fun writeEntry(entry: String) {
        writeEntry(boundedEntry(entry))
    }

    @Synchronized
    private fun writeEntry(entry: ByteArray) {
        // Persist the sparse incident signal first so a failure in the noisy
        // rolling file does not discard the only reconnect evidence as well.
        val text = entry.toString(Charsets.UTF_8)
        if (text.contains("ws_lifecycle ")) appendWebSocketLifecycleEntry(text)
        // Retry failed pruning before allocating another file. Files that cannot
        // be removed must not turn a disk error into unbounded new-file creation.
        pruneOldFiles(currentFile)
        if (!currentFile.isFile || currentFile.length() + entry.size > MAX_FILE_SIZE) {
            rotate()
        }
        currentFile.appendBytes(entry)
    }

    private fun boundedEntry(text: String, truncated: Boolean = false): ByteArray {
        // Limit chars before encoding too; one huge log call must not allocate
        // a second equally huge UTF-8 buffer just to decide it is oversized.
        val bytes = text.take(MAX_ENTRY_BYTES).toByteArray(Charsets.UTF_8)
        if (!truncated && text.length <= MAX_ENTRY_BYTES && bytes.size <= MAX_ENTRY_BYTES) return bytes
        val suffix = TRUNCATED_ENTRY.toByteArray(Charsets.UTF_8)
        val prefix = decodeUtf8(bytes, minOf(bytes.size, MAX_ENTRY_BYTES - suffix.size))
        return prefix.toByteArray(Charsets.UTF_8) + suffix
    }

    private fun decodeUtf8(bytes: ByteArray, count: Int = bytes.size): String =
        Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.IGNORE)
            .onUnmappableCharacter(CodingErrorAction.IGNORE)
            .decode(ByteBuffer.wrap(bytes, 0, count)).toString()

    private class BoundedLogWriter(private val limit: Int) : Writer() {
        private val buffer = StringBuilder()
        var truncated = false
            private set
        val text: String get() = buffer.toString()

        override fun write(chars: CharArray, offset: Int, length: Int) {
            val count = minOf(length, limit - buffer.length)
            if (count > 0) buffer.append(chars, offset, count)
            if (count < length) truncated = true
        }

        override fun write(text: String, offset: Int, length: Int) {
            val count = minOf(length, limit - buffer.length)
            if (count > 0) buffer.append(text, offset, offset + count)
            if (count < length) truncated = true
        }

        override fun flush() = Unit
        override fun close() = Unit
    }

    private fun appendWebSocketLifecycleEntry(entry: String) {
        // Lifecycle events are generated as one structured line. Do not copy a
        // possible throwable stack trace into the priority sidecar.
        val line = entry.substringBefore('\n').let { "$it\n" }.toByteArray(Charsets.UTF_8)
        if (line.size > MAX_WS_LIFECYCLE_FILE_BYTES) return
        synchronized(wsLifecycleLock) {
            runCatching {
                var existing = if (wsLifecycleFile.isFile) wsLifecycleFile.readBytes() else ByteArray(0)
                if (existing.size + line.size > MAX_WS_LIFECYCLE_FILE_BYTES) {
                    val retainBytes = minOf(
                        RETAIN_WS_LIFECYCLE_FILE_BYTES,
                        MAX_WS_LIFECYCLE_FILE_BYTES - line.size,
                    )
                    val keepFrom = (existing.size - retainBytes).coerceAtLeast(0)
                    val lineStart = if (keepFrom == 0) 0 else {
                        val nextLine = indexOfLineFeed(existing, keepFrom)
                        if (nextLine < 0) existing.size else nextLine + 1
                    }
                    existing = existing.copyOfRange(lineStart, existing.size)
                }
                wsLifecycleFile.writeBytes(existing + line)
            }.onFailure { error ->
                System.err.println("Sphere lifecycle log write error: ${error.javaClass.simpleName}")
            }
        }
    }

    private fun indexOfLineFeed(bytes: ByteArray, start: Int): Int {
        for (index in start.coerceAtLeast(0) until bytes.size) {
            if (bytes[index] == '\n'.code.toByte()) return index
        }
        return -1
    }

    private fun rotate() {
        currentFile = newLogFile()
        pruneOldFiles(currentFile)
    }

    private fun pruneOldFiles(active: File) {
        val files = logFiles().sortedWith(fileOrder)
        if (files.size > MAX_FILE_COUNT) {
            files.filter { it != active }.take(files.size - MAX_FILE_COUNT).forEach {
                if (!it.delete() && it.exists()) throw IOException("Cannot prune owned log file")
            }
        }
    }

    private fun logFiles(): List<File> =
        logDir.listFiles { f -> f.isFile && f.name.startsWith(LOG_PREFIX) && f.name.endsWith(LOG_EXT) }
            ?.toList() ?: emptyList()

    private fun resolveCurrentFile(): File {
        val newest = logFiles().maxWithOrNull(fileOrder)
        val active = newest?.takeIf { it.length() < MAX_FILE_SIZE } ?: newLogFile()
        // Bound migration I/O to retained files rather than every historical log.
        pruneOldFiles(active)
        // Migrate files produced by older versions, retaining newest valid UTF-8
        // bytes with a bounded buffer rather than reading an oversized whole file.
        for (file in logFiles()) {
            if (file.length() <= MAX_FILE_SIZE) continue
            val timestamp = file.lastModified()
            RandomAccessFile(file, "rw").use { stream ->
                val bytes = ByteArray(MAX_FILE_SIZE.toInt())
                stream.seek(stream.length() - bytes.size)
                stream.readFully(bytes)
                val tail = decodeUtf8(bytes).toByteArray(Charsets.UTF_8)
                stream.seek(0)
                stream.write(tail)
                stream.setLength(tail.size.toLong())
            }
            // Repair must not make an old file newer than the latest incident.
            file.setLastModified(timestamp)
        }
        return active
    }

    private fun newLogFile(): File {
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
        while (true) {
            val file = File(logDir, "$LOG_PREFIX${ts}_${(fileSequence++).toString().padStart(6, '0')}$LOG_EXT")
            // Atomic creation establishes uniqueness and makes quota pruning see
            // the new file before its first append, even within the same millisecond.
            if (file.createNewFile()) return file
        }
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
