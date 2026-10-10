package com.sphereplatform.agent.commands

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Assume
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.file.Files
import java.util.concurrent.atomic.AtomicInteger
import java.util.zip.CRC32
import java.util.zip.DeflaterOutputStream

/** Small valid PNG, not a screenshot/UI mock. Used to exercise container/retention IO. */
internal fun screenshotFixture(): ByteArray {
    val bytes = ByteArrayOutputStream()
    val output = DataOutputStream(bytes)
    output.write(byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10))
    fun chunk(type: String, data: ByteArray) {
        val name = type.toByteArray()
        output.writeInt(data.size)
        output.write(name)
        output.write(data)
        output.writeInt(CRC32().apply { update(name); update(data) }.value.toInt())
    }
    val header = ByteArrayOutputStream()
    DataOutputStream(header).apply { writeInt(1); writeInt(1); write(byteArrayOf(8, 6, 0, 0, 0)) }
    chunk("IHDR", header.toByteArray())
    val compressed = ByteArrayOutputStream()
    DeflaterOutputStream(compressed).use { it.write(byteArrayOf(0, 10, 20, 30, 255.toByte())) }
    chunk("IDAT", compressed.toByteArray())
    chunk("IEND", byteArrayOf())
    return bytes.toByteArray()
}

class ScreenshotFileStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private val directory get() = File(temporary.root, "dag-screenshots-v1")

    @Test fun `original encoded PNG bytes and UUID path are preserved`() = runBlocking {
        val bytes = screenshotFixture()
        val path = ScreenshotFileStore(directory).capture { it.writeBytes(bytes) }
        assertArrayEquals(bytes, path.readBytes())
        assertEquals(directory.canonicalFile, checkNotNull(path.parentFile).canonicalFile)
        assertTrue(path.name.startsWith("capture-"))
        assertFalse(path.path.contains("sdcard"))
        assertEquals(1, directory.listFiles()!!.size)
    }

    @Test fun `repeated captures keep eight committed files and evict oldest owned file`() = runBlocking {
        var now = 1_000_000L
        val store = ScreenshotFileStore(directory) { now }
        val first = store.capture { it.writeBytes(screenshotFixture()) }
        repeat(19) { now += 1_000; store.capture { it.writeBytes(screenshotFixture()) } }
        val files = directory.listFiles()!!
        assertEquals(8, files.size)
        assertFalse(first.exists())
        assertTrue(files.all { it.name.startsWith("capture-") })
        assertTrue(files.sumOf { it.length() } <= ScreenshotFileStore.MAX_FILES * ScreenshotFileStore.MAX_BYTES)
    }

    @Test fun `expired and orphan staging are removed on next capture but foreign names survive`() = runBlocking {
        var now = 1_000_000L
        val store = ScreenshotFileStore(directory) { now }
        val expired = store.capture { it.writeBytes(screenshotFixture()) }
        val foreign = File(directory, "family-photo.png").apply { writeText("untouched") }
        val staging = File(directory, "pending-00000000-0000-0000-0000-000000000000.png").apply { writeText("partial") }
        now += ScreenshotFileStore.MAX_AGE_MS
        store.capture { it.writeBytes(screenshotFixture()) }
        assertFalse(expired.exists())
        assertFalse(staging.exists())
        assertEquals("untouched", foreign.readText())
        assertEquals(2, directory.listFiles()!!.size)
    }

    @Test fun `oversized native output is rejected and staging removed`() = runBlocking {
        assertThrows(IOException::class.java) {
            runBlocking {
                ScreenshotFileStore(directory).capture { file ->
                    RandomAccessFile(file, "rw").use { it.setLength(ScreenshotFileStore.MAX_BYTES + 1) }
                }
            }
        }
        assertEquals(0, directory.listFiles()!!.size)
    }

    @Test fun `truncated bad CRC non PNG and trailing payload never publish`() = runBlocking {
        val valid = screenshotFixture()
        val badCrc = valid.copyOf().apply { this[29] = (this[29].toInt() xor 1).toByte() }
        for (bad in listOf(valid.copyOf(valid.size - 1), badCrc, ByteArray(80), valid + byteArrayOf(1))) {
            assertThrows(IOException::class.java) { runBlocking { ScreenshotFileStore(directory).capture { it.writeBytes(bad) } } }
            assertEquals(0, directory.listFiles()!!.size)
        }
    }

    @Test fun `failed and cancelled writer removes staging and releases capture ownership`() = runBlocking {
        val store = ScreenshotFileStore(directory)
        assertThrows(IOException::class.java) { runBlocking { store.capture { it.writeText("partial"); throw IOException("writer failed") } } }
        val entered = CompletableDeferred<Unit>()
        val job = launch { store.capture { it.writeText("partial"); entered.complete(Unit); awaitCancellation() } }
        entered.await()
        job.cancelAndJoin()
        assertEquals(0, directory.listFiles()!!.size)
        assertTrue(store.capture { it.writeBytes(screenshotFixture()) }.exists())
    }

    @Test fun `valid CRC cannot bypass dimension and PNG header bounds`() = runBlocking {
        for (mutation in listOf<(ByteArray) -> Unit>(
            { java.nio.ByteBuffer.wrap(it, 16, 4).putInt(9000) },
            { it[24] = 0 },
            { it[25] = 9 },
            { it[28] = 2 },
        )) {
            val bytes = screenshotFixture()
            mutation(bytes)
            val crc = CRC32().apply { update(bytes, 12, 17) }.value.toInt()
            java.nio.ByteBuffer.wrap(bytes, 29, 4).putInt(crc)
            assertThrows(IOException::class.java) { runBlocking { ScreenshotFileStore(directory).capture { it.writeBytes(bytes) } } }
            assertEquals(0, directory.listFiles()!!.size)
        }
    }

    @Test fun `concurrent requests serialize the native writer and maintain retention`() = runBlocking {
        val store = ScreenshotFileStore(directory)
        val active = AtomicInteger()
        val maximum = AtomicInteger()
        coroutineScope {
            (1..20).map { async(Dispatchers.Default) {
                store.capture {
                    val count = active.incrementAndGet()
                    maximum.updateAndGet { old -> maxOf(old, count) }
                    delay(5)
                    it.writeBytes(screenshotFixture())
                    active.decrementAndGet()
                }
            } }.awaitAll()
        }
        assertEquals(1, maximum.get())
        assertEquals(8, directory.listFiles()!!.size)
    }

    @Test fun `owned-looking symlink blocks capture without deleting external target`() {
        directory.mkdirs()
        val target = temporary.newFile("outside.png").apply { writeText("keep") }
        symlink(File(directory, "capture-00000000-0000-0000-0000-000000000000.png"), target)
        assertThrows(IOException::class.java) { runBlocking { ScreenshotFileStore(directory).capture { fail("Writer must not start") } } }
        assertEquals("keep", target.readText())
    }

    @Test fun `store directory symlink is rejected before any write`() {
        val target = temporary.newFolder("outside")
        symlink(directory, target)
        assertThrows(IOException::class.java) { runBlocking { ScreenshotFileStore(directory).capture { fail("Writer must not start") } } }
        assertEquals(0, target.listFiles()!!.size)
    }

    @Test fun `clock reversal cannot grow file count beyond budget`() = runBlocking {
        var now = 1_000_000L
        val store = ScreenshotFileStore(directory) { now }
        repeat(15) { store.capture { it.writeBytes(screenshotFixture()) }; now -= 1_000 }
        assertEquals(8, directory.listFiles()!!.size)
    }

    @Test fun `owned-looking directory is never recursively deleted`() {
        directory.mkdirs()
        val nested = File(directory, "capture-00000000-0000-0000-0000-000000000000.png").apply { mkdir() }
        val child = File(nested, "keep.txt").apply { writeText("untouched") }
        assertThrows(IOException::class.java) { runBlocking { ScreenshotFileStore(directory).capture { fail("Writer must not start") } } }
        assertEquals("untouched", child.readText())
    }

    private fun symlink(link: File, target: File) {
        try {
            Files.createSymbolicLink(link.toPath(), target.toPath())
        } catch (failure: java.nio.file.FileSystemException) {
            if (!System.getProperty("os.name").startsWith("Windows")) throw failure
            // Windows needs an OS privilege. Ubuntu Android CI must run both guards.
            Assume.assumeNoException("Windows symlink creation privilege unavailable", failure)
        }
    }
}
