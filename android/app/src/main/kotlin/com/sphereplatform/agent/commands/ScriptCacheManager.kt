package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import kotlinx.serialization.json.JsonPrimitive
import timber.log.Timber
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Продакшн-кеш DAG-скриптов на устройстве.
 *
 * ## Принцип работы (Content-Addressable Cache)
 * Скрипт идентифицируется двумя параметрами:
 *  - **name** — человеко-читаемое имя (ключ хранения, например "daily_login")
 *  - **hash** — SHA-256 hex от канонического тела DAG-скрипта, вычисляется
 *    на стороне **сервера** и передаётся в payload EXECUTE_DAG
 *
 * **Алгоритм при каждом запуске скрипта:**
 * ```
 * 1. Сервер присылает dag_name + dag_hash (+ опционально dag-тело)
 * 2. Агент ищет в кеше запись по name
 *    a. CACHE HIT (hash совпадает)  → запускаем прямо из кеша, dag-тело не нужно
 *    b. HASH MISMATCH (запись есть, но hash другой) → скрипт изменился:
 *       обновляем кеш из payload, запускаем новую версию
 *    c. CACHE MISS (записи нет) → кешируем из payload, запускаем
 * ```
 *
 * ## Хранение
 * `EncryptedSharedPreferences` (AES256-GCM). Каждая запись:
 * ```json
 * {
 *   "hash":      "e3b0c44298fc1c149afb...",   // SHA-256 hex
 *   "dag":       { ... },                       // полный DAG JSON
 *   "cached_at": 1740000000000                  // Unix ms
 * }
 * ```
 * Индекс (LRU-порядок имён) хранится под отдельным ключом [KEY_INDEX].
 *
 * ## Eviction
 * LRU: при переполнении ([MAX_ENTRIES]) вытесняется наименее недавно
 * использованная запись. Каждое [get]-попадание обновляет позицию в очереди.
 */
@Singleton
class ScriptCacheManager @Inject constructor(
    private val prefs: SharedPreferences,
) {

    companion object {
        private const val KEY_PREFIX  = "script_cache_"
        /**
         * JSON-массив имён в LRU-порядке (хвост = наиболее свежий).
         * Пример: ["old_script", "medium_script", "recent_script"]
         */
        private const val KEY_INDEX   = "script_cache_lru_index"
        /** Максимальное количество скриптов в кеше. */
        private const val MAX_ENTRIES = 20
    }

    private val json = Json { ignoreUnknownKeys = true }

    // ── Публичный API ────────────────────────────────────────────────────────

    /**
     * Результат поиска скрипта в кеше.
     */
    sealed class CacheResult {
        /** Скрипт найден, аутентичен — можно запускать напрямую. */
        data class Hit(
            val dag: JsonObject,
            /** Штамп времени кеширования (Unix ms). */
            val cachedAt: Long,
        ) : CacheResult()

        /**
         * Скрипт с таким именем есть в кеше, но hash не совпадает:
         * скрипт изменился (новая версия). Агент должен взять dag из payload
         * и обновить кеш через [put].
         */
        data class HashMismatch(val cachedHash: String) : CacheResult()

        /** Скрипта с таким именем нет в кеше. */
        object Miss : CacheResult()
    }

    /**
     * Метаданные об одном закешированном скрипте (для диагностики / UI).
     */
    data class CachedScriptMeta(
        val name: String,
        val hash: String,
        val cachedAt: Long,
    )

    /**
     * Ищет скрипт в кеше по имени и проверяет актуальность hash.
     *
     * @param name      Имя скрипта (поле `dag_name` в payload).
     * @param expectedHash SHA-256 hex, присланный сервером.
     * @return [CacheResult.Hit] если скрипт свежий,
     *         [CacheResult.HashMismatch] если устаревший,
     *         [CacheResult.Miss] если отсутствует.
     */
    fun get(name: String, expectedHash: String): CacheResult {
        val raw = prefs.getString("$KEY_PREFIX$name", null)
            ?: return CacheResult.Miss

        val entry = runCatching { json.parseToJsonElement(raw).jsonObject }
            .onFailure {
                Timber.w("[ScriptCache] Повреждённая запись name='$name' — удаляем")
                evict(name)
            }
            .getOrNull() ?: return CacheResult.Miss

        val cachedHash = entry["hash"]?.jsonPrimitive?.content ?: return CacheResult.Miss
        if (!cachedHash.equals(expectedHash, ignoreCase = true)) {
            Timber.i("[ScriptCache] HASH MISMATCH name='$name': cached=${cachedHash.take(8)}… expected=${expectedHash.take(8)}…")
            return CacheResult.HashMismatch(cachedHash)
        }

        val dag = entry["dag"]?.jsonObject ?: run {
            Timber.w("[ScriptCache] Нет поля 'dag' в записи name='$name' — удаляем")
            evict(name)
            return CacheResult.Miss
        }
        val cachedAt = runCatching { entry["cached_at"]!!.jsonPrimitive.long }.getOrDefault(0L)

        // Обновляем LRU-позицию при каждом попадании
        touchLru(name)

        Timber.i("[ScriptCache] HIT name='$name' hash=${expectedHash.take(8)}… cachedAt=$cachedAt")
        return CacheResult.Hit(dag, cachedAt)
    }

    /**
     * Сохраняет скрипт в кеш (или перезаписывает устаревшую версию).
     *
     * @param name   Имя скрипта.
     * @param hash   SHA-256 hex, присланный сервером (сохраняется as-is).
     * @param dag    Тело DAG-скрипта.
     */
    fun put(name: String, hash: String, dag: JsonObject) {
        val entry = buildJsonObject {
            put("hash", hash)
            put("dag", dag)
            put("cached_at", System.currentTimeMillis())
        }

        // LRU eviction: удаляем самую старую запись если кеш полон
        val index = readIndex().toMutableList()
        var evictName: String? = null
        if (name !in index && index.size >= MAX_ENTRIES) {
            evictName = index.removeFirst()
            Timber.i("[ScriptCache] LRU evict: '$evictName' (лимит $MAX_ENTRIES достигнут)")
        }
        index.remove(name)  // убираем старую позицию если была
        index.add(name)     // добавляем в конец (самый свежий)

        // PERF: Один атомарный apply() вместо двух.
        // До: remove().apply() + putString().apply() = 2 crypto-записи (EncryptedSharedPreferences
        // шифрует каждый apply() через AES-GCM). Crash между ними → orphaned data.
        // После: одна запись — 2× быстрее и crash-safe.
        prefs.edit().apply {
            evictName?.let { remove("$KEY_PREFIX$it") }
            putString("$KEY_PREFIX$name", json.encodeToString(entry))
            putString(KEY_INDEX, serializeIndex(index))
        }.apply()

        Timber.i("[ScriptCache] PUT name='$name' hash=${hash.take(8)}… (всего в кеше: ${index.size})")
    }

    /**
     * Удаляет скрипт из кеша по имени.
     *
     * @param name Имя скрипта для удаления.
     */
    fun evict(name: String) {
        val index = readIndex().toMutableList()
        if (index.remove(name)) {
            prefs.edit()
                .remove("$KEY_PREFIX$name")
                .putString(KEY_INDEX, serializeIndex(index))
                .apply()
            Timber.i("[ScriptCache] EVICT name='$name'")
        }
    }

    /**
     * Возвращает список метаданных всех закешированных скриптов (LRU-порядок,
     * хвост = самый свежий). Используется для диагностических команд.
     */
    fun listCached(): List<CachedScriptMeta> {
        return readIndex().mapNotNull { name ->
            val raw = prefs.getString("$KEY_PREFIX$name", null) ?: return@mapNotNull null
            runCatching {
                val entry = json.parseToJsonElement(raw).jsonObject
                CachedScriptMeta(
                    name     = name,
                    hash     = entry["hash"]?.jsonPrimitive?.content ?: "",
                    cachedAt = runCatching { entry["cached_at"]!!.jsonPrimitive.long }.getOrDefault(0L),
                )
            }.getOrNull()
        }
    }

    /**
     * Вычисляет SHA-256 от тела DAG на стороне агента.
     * Используется при необходимости локальной верификации (опционально).
     *
     * @param dagJson DAG для хеширования.
     * @return SHA-256 hex строка нижнего регистра.
     */
    fun computeHash(dagJson: JsonObject): String {
        val bytes = json.encodeToString(dagJson).toByteArray(Charsets.UTF_8)
        return MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }
    }

    // ── Внутренние хелперы ───────────────────────────────────────────────────

    /**
     * Перемещает [name] в конец LRU-индекса (самая свежая позиция).
     * Атомарно обновляет SharedPreferences.
     */
    private fun touchLru(name: String) {
        val index = readIndex().toMutableList()
        if (index.remove(name)) {
            index.add(name)
            prefs.edit().putString(KEY_INDEX, serializeIndex(index)).apply()
        }
    }

    /** Читает LRU-индекс из SharedPreferences. */
    private fun readIndex(): List<String> {
        val raw = prefs.getString(KEY_INDEX, null) ?: return emptyList()
        return runCatching {
            json.parseToJsonElement(raw).jsonArray
                .map { it.jsonPrimitive.content }
        }.getOrElse {
            Timber.w("[ScriptCache] Повреждён LRU-индекс — сброс")
            emptyList()
        }
    }

    /** Сериализует список имён в JSON-массив. */
    private fun serializeIndex(names: List<String>): String {
        val arr: JsonArray = buildJsonArray { names.forEach { add(JsonPrimitive(it)) } }
        return json.encodeToString(arr)
    }
}
