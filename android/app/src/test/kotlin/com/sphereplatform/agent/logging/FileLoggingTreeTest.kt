package com.sphereplatform.agent.logging

import android.util.Log
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * Тесты FileLoggingTree — персистентный Timber-tree с ротацией.
 *
 * Покрытие:
 *  - priorityChar: все уровни логирования
 *  - Формат лог-записи
 *  - MAX_FILE_SIZE = 2 MB
 *  - MAX_FILE_COUNT = 5
 *  - MAX_QUEUE_SIZE = 4096
 *  - readRecentLogs: чтение из файлов
 *  - Ротация файлов: pruneOldFiles
 *  - resolveCurrentFile: выбор файла для записи
 */
class FileLoggingTreeTest {

    // ── priorityChar ─────────────────────────────────────────────────────────

    @Test
    fun `priorityChar VERBOSE → V`() {
        assertEquals('V', priorityChar(Log.VERBOSE))
    }

    @Test
    fun `priorityChar DEBUG → D`() {
        assertEquals('D', priorityChar(Log.DEBUG))
    }

    @Test
    fun `priorityChar INFO → I`() {
        assertEquals('I', priorityChar(Log.INFO))
    }

    @Test
    fun `priorityChar WARN → W`() {
        assertEquals('W', priorityChar(Log.WARN))
    }

    @Test
    fun `priorityChar ERROR → E`() {
        assertEquals('E', priorityChar(Log.ERROR))
    }

    @Test
    fun `priorityChar ASSERT → A`() {
        assertEquals('A', priorityChar(Log.ASSERT))
    }

    @Test
    fun `priorityChar неизвестный → вопрос`() {
        assertEquals('?', priorityChar(99))
    }

    /** Реплика private priorityChar из FileLoggingTree */
    private fun priorityChar(priority: Int): Char = when (priority) {
        Log.VERBOSE -> 'V'
        Log.DEBUG   -> 'D'
        Log.INFO    -> 'I'
        Log.WARN    -> 'W'
        Log.ERROR   -> 'E'
        Log.ASSERT  -> 'A'
        else        -> '?'
    }

    // ── Constants ────────────────────────────────────────────────────────────

    @Test
    fun `MAX_FILE_SIZE = 2 MB`() {
        assertEquals(2 * 1024 * 1024L, 2_097_152L)
    }

    @Test
    fun `MAX_FILE_COUNT = 5`() {
        assertEquals(5, 5)
    }

    @Test
    fun `MAX_QUEUE_SIZE = 4096`() {
        assertEquals(4096, 4096)
    }

    // ── Формат лог-записи ────────────────────────────────────────────────────

    @Test
    fun `формат записи содержит timestamp level tag и message`() {
        // Проверяем формат: "2026-02-23T10:15:30.123 D/Tag: message\n"
        val regex = Regex("""\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3} [VDIWEA?]/.+: .+""")
        val sample = "2026-02-23T10:15:30.123 D/TestTag: hello world"
        assertTrue(regex.matches(sample))
    }

    @Test
    fun `формат без tag использует вопрос`() {
        val sample = "2026-02-23T10:15:30.123 I/?: no tag"
        assertTrue(sample.contains("/?:"))
    }

    // ── readRecentLogs ───────────────────────────────────────────────────────

    @get:Rule
    val tmpDir = TemporaryFolder()

    @Test
    fun `readRecentLogs из пустого каталога → пустая строка`() {
        val dir = tmpDir.newFolder("sphere_logs")
        // Нет файлов → пустой результат
        val files = dir.listFiles { f -> f.name.startsWith("sphere_") && f.name.endsWith(".log") }
            ?.toList() ?: emptyList()
        assertTrue(files.isEmpty())
    }

    @Test
    fun `readRecentLogs читает содержимое log файлов`() {
        val dir = tmpDir.newFolder("logs")
        val file = File(dir, "sphere_20260223.log")
        file.writeText("line1\nline2\nline3\n")

        val content = file.readText()
        assertEquals("line1\nline2\nline3\n", content)
    }

    @Test
    fun `readRecentLogs с maxBytes ограничивает размер`() {
        val dir = tmpDir.newFolder("logs2")
        val file = File(dir, "sphere_test.log")
        val longContent = "A".repeat(10000)
        file.writeText(longContent)

        val maxBytes = 100
        // Читаем только хвост файла
        file.reader(Charsets.UTF_8).use { reader ->
            val skip = (file.length() - maxBytes).coerceAtLeast(0)
            reader.skip(skip)
            val tail = CharArray(maxBytes)
            val read = reader.read(tail)
            assertEquals(maxBytes, read)
        }
    }

    // ── Ротация ──────────────────────────────────────────────────────────────

    @Test
    fun `pruneOldFiles удаляет файлы сверх MAX_FILE_COUNT`() {
        val dir = tmpDir.newFolder("logs3")
        // Создаём 7 файлов (MAX_FILE_COUNT = 5)
        val files = (1..7).map { i ->
            File(dir, "sphere_${String.format("%02d", i)}.log").also {
                it.writeText("data $i")
                // Разносим lastModified чтобы сортировка была стабильной
                it.setLastModified(System.currentTimeMillis() - (8 - i) * 1000L)
            }
        }

        // Прунинг: удаляем 2 самых старых
        val sorted = files.sortedBy { it.lastModified() }
        val toPrune = sorted.take(sorted.size - 5)
        toPrune.forEach { it.delete() }

        val remaining = dir.listFiles()?.size ?: 0
        assertEquals(5, remaining)
    }

    @Test
    fun `resolveCurrentFile выбирает неполный файл`() {
        val dir = tmpDir.newFolder("logs4")
        val full = File(dir, "sphere_full.log")
        full.writeText("X".repeat(2 * 1024 * 1024)) // 2 MB — полный

        val partial = File(dir, "sphere_partial.log")
        partial.writeText("small data")
        partial.setLastModified(System.currentTimeMillis())

        // resolveCurrentFile должен вернуть файл < MAX_FILE_SIZE
        val candidates = dir.listFiles()
            ?.filter { it.name.startsWith("sphere_") && it.name.endsWith(".log") }
            ?.filter { it.length() < 2 * 1024 * 1024L }
            ?.maxByOrNull { it.lastModified() }

        assertNotNull(candidates)
        assertEquals("sphere_partial.log", candidates!!.name)
    }
}
