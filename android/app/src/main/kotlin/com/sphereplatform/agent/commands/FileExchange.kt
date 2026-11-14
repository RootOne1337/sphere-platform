package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.IOException
import java.nio.channels.Channels
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.Path
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.BasicFileAttributes
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.locks.ReentrantLock

internal class FileExchangeFailure(code: String) : IllegalStateException(code)

/** Bounded flat workspace. Only the authenticated file-exchange command reaches this directory. */
internal class FileExchange(private val root: Path) {
    companion object {
        const val VERSION = 1
        const val MAX_FILE_BYTES = 256 * 1024
        private const val MAX_ENCODED_BYTES = (MAX_FILE_BYTES + 2) / 3 * 4
        private const val MAX_FILES = 100
        private const val MAX_WORKSPACE_BYTES = 16L * 1024 * 1024
        private const val TEMP_PREFIX = ".sphere-transfer-"
        private val validName = Regex("[A-Za-z0-9][A-Za-z0-9._ -]{0,119}")
        private val digestPattern = Regex("[0-9a-f]{64}")
        // The dispatcher is a singleton, but the workspace must also be
        // serialized across replacement dispatcher instances in this process.
        private val workspaceLock = ReentrantLock()
    }

    private data class Entry(val name: String, val size: Long, val modifiedAtMs: Long)
    private data class Workspace(val files: List<Entry>, val totalBytes: Long)

    fun execute(payload: JsonObject): JsonObject {
        if (!workspaceLock.tryLock()) fail("file_exchange_busy")
        try {
            val action = payload.string("action")
            val fields = when (action) {
                "list" -> setOf("action")
                "read" -> setOf("action", "name")
                "write" -> setOf("action", "name", "data", "sha256")
                else -> fail("file_exchange_failed")
            }
            if (payload.keys != fields) fail("file_exchange_failed")
            val name = if (action == "list") "" else payload.string("name")
                ?.takeIf(::isValidName) ?: fail("file_invalid_name")
            prepareRoot()
            return when (action) {
                "list" -> list()
                "read" -> read(name)
                else -> write(name, payload)
            }
        } catch (_: IOException) {
            fail("file_exchange_failed")
        } catch (_: SecurityException) {
            fail("file_exchange_failed")
        } catch (_: UnsupportedOperationException) {
            fail("file_exchange_failed")
        } finally {
            workspaceLock.unlock()
        }
    }

    private fun prepareRoot() {
        try {
            Files.createDirectory(root)
        } catch (_: FileAlreadyExistsException) {
            if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) fail("file_exchange_failed")
        }
    }

    private fun scan(): Workspace {
        val files = mutableListOf<Entry>()
        var totalBytes = 0L
        var entries = 0
        Files.newDirectoryStream(root).use { paths ->
            for (path in paths) {
                if (++entries > MAX_FILES + 1) fail("file_quota_exceeded")
                val name = path.fileName.toString()
                val attributes = Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
                if (attributes.isRegularFile && name.startsWith(TEMP_PREFIX) && name.endsWith(".part")) {
                    // A process may be killed before the finally block; a temp
                    // file is never a valid user name or exposed by list/read.
                    Files.deleteIfExists(path)
                    continue
                }
                if (!attributes.isRegularFile || !isValidName(name)) continue
                val size = attributes.size()
                totalBytes += size.coerceAtMost(MAX_WORKSPACE_BYTES)
                files += Entry(name, size, attributes.lastModifiedTime().toMillis().coerceAtLeast(0))
            }
        }
        if (files.size > MAX_FILES) fail("file_quota_exceeded")
        return Workspace(files.sortedBy { it.name }, totalBytes)
    }

    private fun list(): JsonObject {
        val workspace = scan()
        return buildJsonObject {
            put("version", VERSION)
            put("max_bytes", MAX_FILE_BYTES)
            put("files", buildJsonArray {
                for (file in workspace.files) add(buildJsonObject {
                    put("name", file.name)
                    put("size", file.size)
                    put("modified_at_ms", file.modifiedAtMs)
                })
            })
        }
    }

    private fun read(name: String): JsonObject {
        val path = root.resolve(name)
        val content = try {
            val attributes = Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
            if (!attributes.isRegularFile) fail("file_not_found")
            if (attributes.size() > MAX_FILE_BYTES) fail("file_too_large")
            // Bound the actual read too, even if a local writer grows this file.
            Files.newByteChannel(path, setOf(StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)).use { channel ->
                val bytes = ByteArray(MAX_FILE_BYTES + 1)
                val input = Channels.newInputStream(channel)
                var used = 0
                while (used < bytes.size) {
                    val count = input.read(bytes, used, bytes.size - used)
                    if (count < 0) break
                    used += count
                }
                if (used > MAX_FILE_BYTES) fail("file_too_large")
                bytes.copyOf(used)
            }
        } catch (_: NoSuchFileException) {
            fail("file_not_found")
        }
        return fileReceipt(name, content, digest(content), includeData = true)
    }

    private fun write(name: String, payload: JsonObject): JsonObject {
        val encoded = payload.string("data") ?: fail("file_integrity_failed")
        val expected = payload.string("sha256")?.takeIf(digestPattern::matches) ?: fail("file_integrity_failed")
        if (encoded.length > MAX_ENCODED_BYTES) fail("file_too_large")
        val content = try {
            Base64.getDecoder().decode(encoded)
        } catch (_: IllegalArgumentException) {
            fail("file_integrity_failed")
        }
        if (content.size > MAX_FILE_BYTES) fail("file_too_large")
        val actual = digest(content)
        if (actual != expected) fail("file_integrity_failed")

        val target = root.resolve(name)
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) fail("file_exists")
        val workspace = scan()
        if (workspace.files.size >= MAX_FILES || workspace.totalBytes + content.size > MAX_WORKSPACE_BYTES) {
            fail("file_quota_exceeded")
        }
        val staging = Files.createTempFile(root, TEMP_PREFIX, ".part")
        try {
            Files.write(staging, content)
            // Publish with the filesystem's no-overwrite operation. A reader
            // sees either the whole inode or no entry, including after a crash.
            Files.createLink(target, staging)
        } catch (_: FileAlreadyExistsException) {
            fail("file_exists")
        } finally {
            Files.deleteIfExists(staging)
        }
        return fileReceipt(name, content, actual, includeData = false)
    }

    private fun fileReceipt(name: String, content: ByteArray, sha256: String, includeData: Boolean) = buildJsonObject {
        put("name", name)
        put("size", content.size)
        put("sha256", sha256)
        if (includeData) put("data", Base64.getEncoder().encodeToString(content))
    }

    private fun isValidName(name: String) = validName.matches(name) && !name.endsWith('.') && !name.endsWith(' ')

    private fun digest(content: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(content).joinToString("") { "%02x".format(it) }

    private fun JsonObject.string(field: String): String? =
        (this[field] as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun fail(code: String): Nothing = throw FileExchangeFailure(code)
}
