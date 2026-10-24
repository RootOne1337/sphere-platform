package com.sphereplatform.agent.commands

import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.DataInputStream
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.util.UUID
import java.util.zip.CRC32
import kotlin.coroutines.coroutineContext

/** Only this store's UUID files are eligible for deletion. No shared /sdcard sweep. */
internal class ScreenshotFileStore(
    private val directory: File,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    companion object {
        const val MAX_FILES = 8
        const val MAX_BYTES = 5 * 1024 * 1024L
        const val MAX_AGE_MS = 30 * 60 * 1000L
        private val OWNED = Regex("(?:capture-|pending-)[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\\.png")
        private val SIGNATURE = byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10)
    }

    private val ownership = Mutex()
    private val expectedDirectory = directory.absoluteFile

    suspend fun capture(write: suspend (File) -> Unit): File = ownership.withLock {
        coroutineContext.ensureActive()
        ensureDirectory()
        prune(reserveSlot = true)
        val id = UUID.randomUUID().toString()
        val pending = File(directory, "pending-$id.png")
        val published = File(directory, "capture-$id.png")
        requireOwned(pending)
        if (!pending.createNewFile()) throw IOException("screenshot_staging_exists")
        var committed = false
        try {
            write(pending)
            coroutineContext.ensureActive()
            requireOwned(pending)
            validatePng(pending)
            // The writer has acknowledged completion; never publish a blind timed snapshot.
            if (!pending.renameTo(published)) throw IOException("screenshot_publish_failed")
            if (!published.setLastModified(clock())) throw IOException("screenshot_timestamp_failed")
            committed = true
            published
        } finally {
            if (!committed) {
                removeOwned(pending)
                removeOwned(published)
            }
        }
    }

    private fun ensureDirectory() {
        if (directory.canonicalFile != expectedDirectory || Files.isSymbolicLink(directory.toPath())) {
            throw IOException("screenshot_directory_ownership_changed")
        }
        if (!directory.isDirectory && !directory.mkdirs()) throw IOException("screenshot_directory_unavailable")
    }

    private fun requireOwned(file: File) {
        if (file.parentFile?.absoluteFile != expectedDirectory || !OWNED.matches(file.name) ||
            Files.isSymbolicLink(file.toPath()) || file.canonicalFile != file.absoluteFile ||
            (file.exists() && !file.isFile)
        ) throw IOException("screenshot_file_ownership_changed")
    }

    private fun removeOwned(file: File) {
        requireOwned(file)
        if (file.exists() && !file.delete()) throw IOException("screenshot_cleanup_failed")
    }

    private fun prune(reserveSlot: Boolean) {
        val files = directory.listFiles() ?: throw IOException("screenshot_inventory_unavailable")
        val retained = mutableListOf<File>()
        for (file in files) {
            if (!OWNED.matches(file.name)) continue
            requireOwned(file)
            if (file.name.startsWith("pending-") || file.length() > MAX_BYTES ||
                clock() - file.lastModified() >= MAX_AGE_MS
            ) removeOwned(file) else retained.add(file)
        }
        val keep = MAX_FILES - if (reserveSlot) 1 else 0
        retained.sortedWith(compareBy<File> { it.lastModified() }.thenBy { it.name })
            .take((retained.size - keep).coerceAtLeast(0)).forEach(::removeOwned)
    }

    /** Stream PNG chunk CRCs; at most 8 KiB pixels retained, no decode/re-encoding. */
    private fun validatePng(file: File) {
        val expectedSize = file.length()
        if (expectedSize !in 57..MAX_BYTES) throw IOException("screenshot_size_invalid")
        DataInputStream(file.inputStream().buffered()).use { input ->
            val signature = ByteArray(8)
            input.readFully(signature)
            if (!signature.contentEquals(SIGNATURE)) throw IOException("screenshot_not_png")
            var consumed = 8L
            var first = true
            var imageData = false
            val buffer = ByteArray(8192)
            while (true) {
                val size = input.readInt().toLong() and 0xffffffffL
                val type = ByteArray(4)
                input.readFully(type)
                consumed += 12 + size
                if (consumed > expectedSize || consumed > MAX_BYTES) throw IOException("screenshot_chunk_invalid")
                val kind = String(type, Charsets.US_ASCII)
                if (first && (kind != "IHDR" || size != 13L)) throw IOException("screenshot_header_invalid")
                if (!first && kind == "IHDR") throw IOException("screenshot_header_duplicate")
                val crc = CRC32().apply { update(type) }
                if (first) {
                    val header = ByteArray(13)
                    input.readFully(header)
                    crc.update(header)
                    val dimensions = java.nio.ByteBuffer.wrap(header)
                    val width = dimensions.int
                    val height = dimensions.int
                    if (width !in 1..8192 || height !in 1..8192 || width.toLong() * height > 33_554_432L) {
                        throw IOException("screenshot_dimensions_invalid")
                    }
                    val depths = when (header[9].toInt()) {
                        0 -> setOf(1, 2, 4, 8, 16)
                        2, 4, 6 -> setOf(8, 16)
                        3 -> setOf(1, 2, 4, 8)
                        else -> emptySet()
                    }
                    if (header[8].toInt() !in depths || header[10] != 0.toByte() ||
                        header[11] != 0.toByte() || header[12].toInt() !in 0..1
                    ) throw IOException("screenshot_header_invalid")
                    first = false
                } else {
                    var remaining = size
                    while (remaining > 0) {
                        val count = minOf(remaining, buffer.size.toLong()).toInt()
                        input.readFully(buffer, 0, count)
                        crc.update(buffer, 0, count)
                        remaining -= count
                    }
                }
                if ((input.readInt().toLong() and 0xffffffffL) != crc.value) throw IOException("screenshot_crc_invalid")
                if (kind == "IDAT" && size > 0) imageData = true
                if (kind == "IEND") {
                    if (size != 0L || !imageData || consumed != expectedSize || input.read() != -1 || file.length() != expectedSize) {
                        throw IOException("screenshot_incomplete")
                    }
                    return
                }
            }
        }
    }
}
