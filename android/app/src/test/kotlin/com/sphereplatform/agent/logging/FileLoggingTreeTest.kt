package com.sphereplatform.agent.logging

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Real production tree, files and writer thread; only Android Context is mocked. */
class FileLoggingTreeTest {
    @get:Rule val temporary = TemporaryFolder()
    private lateinit var tree: FileLoggingTree
    private lateinit var directory: File
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = mockk<Context>()
        every { context.filesDir } returns temporary.root
        tree = FileLoggingTree(context)
        directory = File(temporary.root, "sphere_logs")
    }

    @After
    fun stopWriter() {
        // Stop the actual app-lifetime worker, without adding a production test API.
        val field = FileLoggingTree::class.java.getDeclaredField("writerThread").apply { isAccessible = true }
        val thread = field.get(tree) as Thread
        thread.interrupt()
        thread.join(2000)
        assertFalse("Test must not leak a log writer", thread.isAlive)
    }

    private fun fixture(name: String, content: String, timestamp: Long = 1000): File =
        File(directory, "sphere_$name.log").apply {
            writeText(content, Charsets.UTF_8)
            assertTrue(setLastModified(timestamp))
        }

    private fun current(file: File) {
        FileLoggingTree::class.java.getDeclaredField("currentFile").apply { isAccessible = true }
            .set(tree, file)
    }

    private fun write(entry: String) {
        FileLoggingTree::class.java.getDeclaredMethod("writeEntry", String::class.java)
            .apply { isAccessible = true }.invoke(tree, entry)
    }

    @Test
    fun `rotation includes the new file in the five file quota`() {
        stopWriter()
        val old = (1..5).map { fixture("quota-$it", "old-$it\n", it.toLong()) }
        old.last().writeBytes(ByteArray(2 * 1024 * 1024) { 'x'.code.toByte() })
        current(old.last())
        write("AFTER_ROTATION\n")
        assertEquals(5, tree.getLogFiles().size)
        assertFalse(old.first().exists())
        assertTrue(tree.readRecentLogs().endsWith("AFTER_ROTATION\n"))
    }

    @Test
    fun `UTF-8 append rotates before exceeding the byte limit`() {
        stopWriter()
        val active = fixture("nearly-full", "x".repeat(2 * 1024 * 1024 - 4))
        current(active)
        write("Я🚗NEWEST\n")
        assertTrue(tree.getLogFiles().all { it.length() <= 2 * 1024 * 1024 })
        assertEquals((2 * 1024 * 1024 - 4).toLong(), active.length())
        assertTrue(tree.readRecentLogs().endsWith("Я🚗NEWEST\n"))
    }

    @Test
    fun `full files cannot be reused during rapid consecutive rotations`() {
        stopWriter()
        val names = mutableSetOf<String>()
        repeat(8) { index ->
            val active = FileLoggingTree::class.java.getDeclaredField("currentFile")
                .apply { isAccessible = true }.get(tree) as File
            active.writeBytes(ByteArray(2 * 1024 * 1024) { 'x'.code.toByte() })
            write("rotation-$index\n")
            val next = FileLoggingTree::class.java.getDeclaredField("currentFile")
                .apply { isAccessible = true }.get(tree) as File
            assertTrue("Every rotation must create a distinct file", names.add(next.name))
            assertEquals("rotation-$index\n", next.readText())
            assertTrue(tree.getLogFiles().size <= 5)
        }
    }

    @Test
    fun `startup repairs excess old files and preserves unrelated files and sidecar`() {
        stopWriter()
        tree.getLogFiles().forEach { assertTrue(it.delete()) }
        val old = (1..8).map { fixture("startup-$it", "record-$it\n", it.toLong()) }
        val sidecar = File(directory, "ws_lifecycle.log").apply { writeText("incident\n") }
        val unrelated = File(directory, "operator-notes.txt").apply { writeText("keep me") }
        val matchingDirectory = File(directory, "sphere_directory.log").apply { mkdir() }
        File(matchingDirectory, "keep.txt").writeText("unrelated directory")
        tree = FileLoggingTree(context)
        assertEquals(5, tree.getLogFiles().size)
        assertTrue(tree.getLogFiles().all { it.isFile })
        assertFalse(old[2].exists())
        assertTrue(old[3].exists())
        assertEquals("incident\n", sidecar.readText())
        assertEquals("keep me", unrelated.readText())
        assertTrue(File(matchingDirectory, "keep.txt").isFile)
    }

    @Test
    fun `oversized legacy file is capped on startup without damaging UTF-8 tail`() {
        stopWriter()
        tree.getLogFiles().forEach { assertTrue(it.delete()) }
        fixture("oversized", "Я漢🚗".repeat(300000) + "LAST_INCIDENT\n")
        tree = FileLoggingTree(context)
        assertTrue(tree.getLogFiles().all { it.length() <= 2 * 1024 * 1024 })
        assertTrue(tree.readRecentLogs().endsWith("LAST_INCIDENT\n"))
        assertFalse(tree.readRecentLogs().contains('\uFFFD'))
    }

    @Test
    fun `oversized queued entry is bounded UTF-8 and records truncation`() {
        tree.i("Я漢🚗".repeat(300000))
        tree.i("AFTER_OVERSIZED\n")
        awaitMarker("AFTER_OVERSIZED")
        val bytes = tree.getLogFiles().flatMap { it.readBytes().toList() }.toByteArray()
        assertTrue("A single log call must not consume megabytes", bytes.size < 17 * 1024)
        val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes)).toString()
        assertTrue(text.contains("[log entry truncated]"))
        assertTrue(text.contains("AFTER_OVERSIZED"))
    }

    @Test
    fun `blocked writer retains newest evidence within a four MiB queue budget`() {
        stopWriter()
        repeat(1000) { tree.i("queued-$it " + "Я🚗".repeat(4000)) }
        val queue = FileLoggingTree::class.java.getDeclaredField("queue")
            .apply { isAccessible = true }.get(tree) as java.util.concurrent.LinkedBlockingQueue<*>
        val entries = queue.toList().map { it as ByteArray }
        assertEquals(256, entries.size)
        assertTrue(entries.sumOf { it.size } <= 4 * 1024 * 1024)
        assertTrue(entries.last().toString(Charsets.UTF_8).contains("queued-999"))
        assertFalse(entries.first().toString(Charsets.UTF_8).contains("queued-0 "))
        assertEquals(744L, tree.getDroppedEntryCount())
    }

    @Test
    fun `huge throwable is explicitly truncated and does not fill a log file`() {
        val method = FileLoggingTree::class.java.getDeclaredMethod(
            "log", Int::class.javaPrimitiveType, String::class.java, String::class.java, Throwable::class.java,
        ).apply { isAccessible = true }
        method.invoke(tree, android.util.Log.ERROR, "test", "THROWABLE", RuntimeException("Я🚗".repeat(300000)))
        tree.i("AFTER_THROWABLE")
        awaitMarker("AFTER_THROWABLE")
        assertTrue(tree.getLogFiles().sumOf { it.length() } < 17 * 1024)
        assertTrue(tree.readRecentLogs().contains("[log entry truncated]"))
    }

    @Test
    fun `empty directory and unrelated files return empty logs`() {
        File(directory, "unrelated.txt").writeText("not an app log")
        assertEquals("", tree.readRecentLogs())
    }

    @Test
    fun `ASCII tail preserves latest marker within byte budget`() {
        fixture("ascii", "old".repeat(10000) + "LATEST_ASCII\n")
        val tail = tree.readRecentLogs(100)
        assertTrue(tail.endsWith("LATEST_ASCII\n"))
        assertEquals(100, tail.toByteArray(Charsets.UTF_8).size)
    }

    @Test
    fun `large Cyrillic log does not skip past the newest records`() {
        fixture("unicode", "Соединение потеряно 🚗\n".repeat(10000) + "LATEST_RECONNECT_OK\n")
        val tail = tree.readRecentLogs(64 * 1024)
        assertTrue("Last event must survive a large UTF-8 prefix", tail.endsWith("LATEST_RECONNECT_OK\n"))
        assertTrue(tail.toByteArray(Charsets.UTF_8).size <= 64 * 1024)
        assertFalse(tail.contains('\uFFFD'))
    }

    @Test
    fun `rotated files share one byte budget rather than character budget`() {
        fixture("older", "x".repeat(100), 1000)
        fixture("newer", "Я".repeat(40), 2000)
        val tail = tree.readRecentLogs(100)
        assertEquals("x".repeat(20) + "Я".repeat(40), tail)
        assertEquals(100, tail.toByteArray(Charsets.UTF_8).size)
    }

    @Test
    fun `all UTF-8 cut positions preserve complete characters and latest content`() {
        val content = "old:Я漢🚗:LATEST\n"
        fixture("boundaries", content)
        for (limit in 1..content.toByteArray(Charsets.UTF_8).size) {
            val tail = tree.readRecentLogs(limit)
            assertTrue("Output exceeds $limit bytes", tail.toByteArray(Charsets.UTF_8).size <= limit)
            assertFalse("Malformed UTF-8 at limit $limit", tail.contains('\uFFFD'))
            assertTrue("Tail is not a suffix at limit $limit", content.endsWith(tail))
            assertTrue(tail.endsWith("\n"))
        }
    }

    @Test
    fun `truncated UTF-8 write does not inflate response with replacement characters`() {
        val file = fixture("partial", "OK\n")
        file.appendBytes(byteArrayOf(0xF0.toByte(), 0x9F.toByte()))
        assertEquals("OK\n", tree.readRecentLogs(5))
    }

    @Test
    fun `logs spanning rotations remain oldest first`() {
        fixture("a", "one\n", 1000)
        fixture("b", "two\n", 2000)
        fixture("c", "three\n", 3000)
        assertEquals("one\ntwo\nthree\n", tree.readRecentLogs(100))
        assertEquals("three\n", tree.readRecentLogs(6))
    }

    @Test
    fun `nonpositive budgets are empty and oversized requests are capped`() {
        fixture("large", "x".repeat(400000) + "LATEST\n")
        assertEquals("", tree.readRecentLogs(0))
        assertEquals("", tree.readRecentLogs(-1))
        val tail = tree.readRecentLogs(Int.MAX_VALUE)
        assertEquals(256 * 1024, tail.toByteArray(Charsets.UTF_8).size)
        assertTrue(tail.endsWith("LATEST\n"))
    }

    @Test
    fun `real asynchronous writer includes timestamp level tag and message`() {
        tree.w("RECONNECT_NATIVE_TREE")
        awaitMarker("RECONNECT_NATIVE_TREE")
        val tail = tree.readRecentLogs()
        assertTrue(tail.contains(" W/?: RECONNECT_NATIVE_TREE\n"))
        assertTrue(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}").containsMatchIn(tail))
    }

    @Test
    fun `websocket lifecycle evidence survives noisy regular log tail`() {
        val event = "ws_lifecycle event=onFailure attempt_id=incident-42 route_slot=1 route_count=2 phase=authenticated elapsed_ms=9001 error_type=SocketTimeoutException"
        tree.i(event)
        awaitLifecycleMarker("incident-42")

        repeat(600) { index -> tree.i("routine-heartbeat-$index " + "x".repeat(160)) }
        awaitMarker("routine-heartbeat-599")

        assertFalse("the routine tail must reproduce the observed truncation", tree.readRecentLogs(32 * 1024).contains("incident-42"))
        val priority = tree.readRecentWebSocketLifecycleLogs(32 * 1024)
        assertTrue("sparse transport evidence must remain available for the next upload", priority.contains("incident-42"))
        assertTrue(priority.contains("error_type=SocketTimeoutException"))
        assertTrue(priority.toByteArray(Charsets.UTF_8).size <= 32 * 1024)
    }

    @Test
    fun `websocket lifecycle sidecar is bounded and keeps the newest records`() {
        repeat(140) { index ->
            tree.i(
                "ws_lifecycle event=onFailure attempt_id=incident-$index route_slot=0 " +
                    "phase=pre_auth error_type=IOException detail=${"x".repeat(512)}",
            )
        }
        awaitLifecycleMarker("incident-139")

        val priority = tree.readRecentWebSocketLifecycleLogs(Int.MAX_VALUE)
        assertTrue(priority.contains("incident-139"))
        assertFalse(priority.contains("incident-0 "))
        assertTrue(priority.toByteArray(Charsets.UTF_8).size <= 64 * 1024)
    }

    @Test
    fun `concurrent UTF-8 writes and reads preserve final marker and bounded responses`() {
        val workers = Executors.newFixedThreadPool(2)
        try {
            val writer = workers.submit {
                repeat(300) { tree.i("строка 🚗 $it") }
                tree.i("FINAL_CONCURRENT_MARKER")
            }
            val reader = workers.submit {
                repeat(300) {
                    val tail = tree.readRecentLogs(127)
                    assertTrue(tail.toByteArray(Charsets.UTF_8).size <= 127)
                    assertFalse(tail.contains('\uFFFD'))
                }
            }
            writer.get(5, TimeUnit.SECONDS)
            reader.get(5, TimeUnit.SECONDS)
            awaitMarker("FINAL_CONCURRENT_MARKER")
        } finally {
            workers.shutdownNow()
            assertTrue(workers.awaitTermination(5, TimeUnit.SECONDS))
        }
    }

    private fun awaitMarker(marker: String) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!tree.readRecentLogs().contains(marker) && System.nanoTime() < deadline) Thread.sleep(5)
        assertTrue("Writer did not persist $marker", tree.readRecentLogs().contains(marker))
    }

    private fun awaitLifecycleMarker(marker: String) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!tree.readRecentWebSocketLifecycleLogs().contains(marker) && System.nanoTime() < deadline) Thread.sleep(5)
        assertTrue("Writer did not persist lifecycle marker $marker", tree.readRecentWebSocketLifecycleLogs().contains(marker))
    }
}
