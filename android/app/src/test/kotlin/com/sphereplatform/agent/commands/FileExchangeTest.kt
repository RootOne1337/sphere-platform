package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class FileExchangeTest {
    @get:Rule val temp = TemporaryFolder()

    private val workspace: Path
        get() = temp.root.toPath().resolve("sphere-exchange")

    private fun request(action: String, name: String? = null, bytes: ByteArray? = null, sha: String? = null) =
        buildJsonObject {
            put("action", action)
            if (name != null) put("name", name)
            if (bytes != null) {
                put("data", Base64.getEncoder().encodeToString(bytes))
                put("sha256", sha ?: digest(bytes))
            }
        }

    private fun digest(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun assertFailure(code: String, run: () -> Unit) {
        assertEquals(code, assertThrows(FileExchangeFailure::class.java, run).message)
    }

    @Test fun `bytes and hash round trip and sorted catalog survive provider recreation`() {
        val provider = FileExchange(workspace)
        val content = byteArrayOf(0, -1, 1, 127, -128)
        assertEquals(1, provider.execute(request("list")).getValue("version").jsonPrimitive.content.toInt())
        val receipt = provider.execute(request("write", "a sample.bin", content))
        assertEquals(setOf("name", "size", "sha256"), receipt.keys)
        assertEquals(digest(content), receipt.getValue("sha256").jsonPrimitive.content)
        provider.execute(request("write", "0.txt", byteArrayOf()))

        val restarted = FileExchange(workspace)
        val listing = restarted.execute(request("list"))
        assertEquals(FileExchange.MAX_FILE_BYTES.toString(), listing.getValue("max_bytes").jsonPrimitive.content)
        assertEquals(listOf("0.txt", "a sample.bin"), listing.getValue("files").jsonArray.map {
            it.jsonObject.getValue("name").jsonPrimitive.content
        })
        val download = restarted.execute(request("read", "a sample.bin"))
        assertEquals(digest(content), download.getValue("sha256").jsonPrimitive.content)
        assertArrayEquals(content, Base64.getDecoder().decode(download.getValue("data").jsonPrimitive.content))
        assertEquals("", restarted.execute(request("read", "0.txt")).getValue("data").jsonPrimitive.content)
    }

    @Test fun `unexpected fields invalid names and corrupt writes produce fixed errors`() {
        val provider = FileExchange(workspace)
        listOf("../private", "a/child", "a\\child", ".hidden", "bad.", "bad ", "файл", "a".repeat(121), "C:boot").forEach {
            assertFailure("file_invalid_name") { provider.execute(request("write", it, byteArrayOf(1))) }
        }
        val corrupt = request("write", "valid.bin", byteArrayOf(1), "0".repeat(64))
        assertFailure("file_integrity_failed") { provider.execute(corrupt) }
        val invalidBase64 = JsonObject(corrupt + ("data" to kotlinx.serialization.json.JsonPrimitive("!")))
        assertFailure("file_integrity_failed") { provider.execute(invalidBase64) }
        assertFailure("file_exchange_failed") { provider.execute(request("list", "not-allowed")) }
        assertFailure("file_not_found") { provider.execute(request("read", "valid.bin")) }
        assertFalse(Files.exists(workspace.resolve("valid.bin")))
    }

    @Test fun `write never replaces the target and startup cleans partial files`() {
        Files.createDirectory(workspace)
        val stale = Files.write(workspace.resolve(".sphere-transfer-previous.part"), byteArrayOf(2))
        val provider = FileExchange(workspace)
        provider.execute(request("write", "existing", byteArrayOf(5)))
        assertFalse(Files.exists(stale))
        assertFailure("file_exists") { provider.execute(request("write", "existing", byteArrayOf(8))) }
        assertArrayEquals(byteArrayOf(5), Files.readAllBytes(workspace.resolve("existing")))
    }

    @Test fun `file size and workspace file count are bounded`() {
        val provider = FileExchange(workspace)
        assertFailure("file_too_large") {
            provider.execute(request("write", "large.bin", ByteArray(FileExchange.MAX_FILE_BYTES + 1)))
        }
        provider.execute(request("list"))
        repeat(100) { index -> Files.createFile(workspace.resolve("file-$index")) }
        assertEquals(100, provider.execute(request("list")).getValue("files").jsonArray.size)
        assertFailure("file_quota_exceeded") { provider.execute(request("write", "another", byteArrayOf(1))) }
    }

    @Test fun `workspace byte quota includes files from a previous process`() {
        val provider = FileExchange(workspace)
        provider.execute(request("list"))
        Files.newByteChannel(workspace.resolve("previous.bin"), java.nio.file.StandardOpenOption.CREATE_NEW,
            java.nio.file.StandardOpenOption.WRITE).use { channel ->
            channel.position(16L * 1024 * 1024 - 1)
            channel.write(java.nio.ByteBuffer.wrap(byteArrayOf(0)))
        }
        assertFailure("file_quota_exceeded") { provider.execute(request("write", "another", byteArrayOf(1))) }
        assertFailure("file_too_large") { provider.execute(request("read", "previous.bin")) }
    }

    @Test fun `two competing uploads leave exactly one original file`() {
        val pool = Executors.newFixedThreadPool(2)
        val start = CountDownLatch(1)
        try {
            val pending = (1..2).map { value -> pool.submit<String> {
                start.await()
                try {
                    FileExchange(workspace).execute(request("write", "race.bin", byteArrayOf(value.toByte())))
                    "completed"
                } catch (e: FileExchangeFailure) {
                    checkNotNull(e.message)
                }
            } }
            start.countDown()
            val outcomes = pending.map { it.get(10, TimeUnit.SECONDS) }
            assertEquals(1, outcomes.count { it == "completed" })
            assertTrue(outcomes.any { it == "file_exists" || it == "file_exchange_busy" })
            assertEquals(1, Files.readAllBytes(workspace.resolve("race.bin")).size)
        } finally {
            pool.shutdownNow()
        }
    }

    @Test fun `read and write refuse symbolic links inside the workspace`() {
        val target = Files.write(temp.root.toPath().resolve("private"), byteArrayOf(9))
        Files.createDirectory(workspace)
        try {
            Files.createSymbolicLink(workspace.resolve("linked"), target)
        } catch (e: IOException) {
            assumeNoException(e)
        } catch (e: UnsupportedOperationException) {
            assumeNoException(e)
        }
        val provider = FileExchange(workspace)
        assertEquals(0, provider.execute(request("list")).getValue("files").jsonArray.size)
        assertFailure("file_not_found") { provider.execute(request("read", "linked")) }
        assertFailure("file_exists") { provider.execute(request("write", "linked", byteArrayOf(1))) }
        assertArrayEquals(byteArrayOf(9), Files.readAllBytes(target))
    }
}
