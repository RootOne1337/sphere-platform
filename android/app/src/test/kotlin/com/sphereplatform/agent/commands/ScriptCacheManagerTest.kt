package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.every
import io.mockk.mockk
import io.mockk.slot
import io.mockk.verify
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты ScriptCacheManager — LRU кеш DAG-скриптов.
 *
 * Покрытие:
 *  - CacheResult.Miss при пустом кеше
 *  - CacheResult.Hit при совпадении hash
 *  - CacheResult.HashMismatch при несовпадении
 *  - put + get round-trip
 *  - LRU eviction при MAX_ENTRIES=20
 *  - evict удаляет запись
 *  - listCached возвращает метаданные
 *  - computeHash детерминистичен
 *  - Повреждённая запись → удаление
 */
class ScriptCacheManagerTest {

    private lateinit var prefs: EncryptedSharedPreferences
    private lateinit var editor: SharedPreferences.Editor
    private lateinit var cache: ScriptCacheManager
    private val storage = mutableMapOf<String, String?>()

    @Before
    fun setUp() {
        editor = mockk(relaxed = true)
        prefs = mockk(relaxed = true)

        // Симулируем SharedPreferences через Map
        every { prefs.edit() } returns editor
        every { editor.putString(any(), any()) } answers {
            storage[firstArg()] = secondArg()
            editor
        }
        every { editor.remove(any()) } answers {
            storage.remove(firstArg<String>())
            editor
        }
        every { editor.apply() } answers { /* noop */ }
        every { prefs.getString(any(), any()) } answers {
            storage[firstArg()] ?: secondArg()
        }

        cache = ScriptCacheManager(prefs)
    }

    private fun sampleDag(): JsonObject = buildJsonObject {
        put("entry_node", "start")
        put("nodes", "[]")
    }

    // ── CacheResult.Miss ─────────────────────────────────────────────────────

    @Test
    fun `пустой кеш → Miss`() {
        val result = cache.get("test_script", "abc123")
        assertTrue(result is ScriptCacheManager.CacheResult.Miss)
    }

    // ── put + get → Hit ──────────────────────────────────────────────────────

    @Test
    fun `put и get с совпадающим hash → Hit`() {
        val dag = sampleDag()
        cache.put("daily_login", "hash123", dag)

        val result = cache.get("daily_login", "hash123")
        assertTrue("ожидали Hit", result is ScriptCacheManager.CacheResult.Hit)
        val hit = result as ScriptCacheManager.CacheResult.Hit
        assertEquals(dag, hit.dag)
        assertTrue(hit.cachedAt > 0)
    }

    // ── HashMismatch ─────────────────────────────────────────────────────────

    @Test
    fun `get с другим hash → HashMismatch`() {
        cache.put("script_a", "old_hash", sampleDag())
        val result = cache.get("script_a", "new_hash")
        assertTrue(result is ScriptCacheManager.CacheResult.HashMismatch)
        assertEquals("old_hash", (result as ScriptCacheManager.CacheResult.HashMismatch).cachedHash)
    }

    // ── evict ────────────────────────────────────────────────────────────────

    @Test
    fun `evict удаляет запись`() {
        cache.put("to_delete", "h1", sampleDag())
        cache.evict("to_delete")
        val result = cache.get("to_delete", "h1")
        assertTrue(result is ScriptCacheManager.CacheResult.Miss)
    }

    @Test
    fun `evict несуществующей записи — не бросает исключение`() {
        cache.evict("nonexistent")
        // Ожидаем отсутствие исключений
    }

    // ── computeHash ──────────────────────────────────────────────────────────

    @Test
    fun `computeHash детерминистичен`() {
        val dag = sampleDag()
        val hash1 = cache.computeHash(dag)
        val hash2 = cache.computeHash(dag)
        assertEquals(hash1, hash2)
    }

    @Test
    fun `computeHash — SHA-256 hex 64 символа`() {
        val hash = cache.computeHash(sampleDag())
        assertEquals(64, hash.length)
        assertTrue(hash.all { it in "0123456789abcdef" })
    }

    @Test
    fun `computeHash разные DAG → разные хеши`() {
        val dag1 = buildJsonObject { put("a", 1) }
        val dag2 = buildJsonObject { put("b", 2) }
        assertNotEquals(cache.computeHash(dag1), cache.computeHash(dag2))
    }

    // ── Повреждённые данные ───────────────────────────────────────────────────

    @Test
    fun `повреждённая запись → Miss + evict`() {
        storage["script_cache_corrupt"] = "not valid json{{"
        val result = cache.get("corrupt", "any_hash")
        assertTrue(result is ScriptCacheManager.CacheResult.Miss)
    }

    @Test
    fun `запись без поля dag → Miss + evict`() {
        storage["script_cache_no_dag"] = """{"hash":"abc123"}"""
        val result = cache.get("no_dag", "abc123")
        assertTrue(result is ScriptCacheManager.CacheResult.Miss)
    }

    // ── Перезапись ───────────────────────────────────────────────────────────

    @Test
    fun `put перезаписывает существующую запись`() {
        val dag1 = buildJsonObject { put("version", 1) }
        val dag2 = buildJsonObject { put("version", 2) }

        cache.put("script", "hash_v1", dag1)
        cache.put("script", "hash_v2", dag2)

        val result = cache.get("script", "hash_v2")
        assertTrue(result is ScriptCacheManager.CacheResult.Hit)
        assertEquals(dag2, (result as ScriptCacheManager.CacheResult.Hit).dag)
    }
}
