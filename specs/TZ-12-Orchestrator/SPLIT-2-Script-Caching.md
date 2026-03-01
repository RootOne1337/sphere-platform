# TZ-12 SPLIT-2 — Кеширование DAG-скриптов на агенте с Content-Addressable хешированием

> **Статус:** Draft  
> **Приоритет:** P1 (оптимизация)  
> **Зависимости:** TZ-04 SPLIT-2 (Script CRUD), TZ-07 (Android Agent)

---

## 1. Мотивация

**Текущая проблема:**
- DAG передаётся **inline** в каждой команде `EXECUTE_DAG` через WebSocket
- Типичный размер DAG: 5–40 KB
- При 1000 эмуляторов × 10 запусков/день = **10 000 × 40 KB = 400 MB** трафика на одинаковые DAG
- WebSocket-фреймы > 16 KB фрагментируются → больше round-trips
- Если агент кратковременно offline → DAG теряется вместе с командой (Redis offline queue хранит, но это лишняя нагрузка)

**Целевое состояние:**
- Агент хранит **локальный кеш** DAG-скриптов с **Content-Addressable** идентификатором
- Команда `EXECUTE_DAG` содержит только `dag_hash` (64 байта) вместо полного DAG (40 KB)
- Если хеш совпадает → берём из кеша (экономия 99.8% трафика)
- Если хеш не совпадает → скачиваем новую версию (fallback)
- **Инвалидация по SHA-256** от полного содержимого DAG, не от имени/версии/даты

---

## 2. Идентификатор скрипта: Content-Addressable Hash

### 2.1 Алгоритм хеширования

```
dag_hash = SHA-256( canonical_json(dag) )
```

Где `canonical_json` — детерминистическая JSON-сериализация:
- Ключи отсортированы лексикографически (рекурсивно)
- Без пробелов/отступов
- Числа без trailing zeros
- Строки в Unicode NFC нормализации

### 2.2 Почему SHA-256

| Вариант | Проблема |
|---------|----------|
| Имя скрипта | Одно имя, много версий |
| script_version.id (UUID) | Не привязан к содержимому — rollback создаёт новый UUID с тем же DAG |
| version_number | Не уникален across scripts |
| MD5/CRC32 | Collisions, не криптостойкий |
| **SHA-256** | Collision-proof, fast, 32 bytes, industry standard |

### 2.3 Вычисление на бэкенде

```python
# backend/services/script_service.py
import hashlib, json

def compute_dag_hash(dag: dict) -> str:
    """Content-addressable hash для DAG.
    
    Детерминистическая сериализация: sort_keys + separators.
    Результат: hex SHA-256 (64 символа).
    """
    canonical = json.dumps(dag, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### 2.4 Хранение в БД

```python
# backend/models/script.py — расширение ScriptVersion
class ScriptVersion(Base, UUIDMixin, TimestampMixin):
    # ... существующие поля ...
    dag: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dag_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="SHA-256 от canonical JSON DAG"
    )
```

**Миграция Alembic:**

```python
def upgrade():
    op.add_column("script_versions", sa.Column("dag_hash", sa.String(64), nullable=True))
    # Вычислить dag_hash для всех существующих записей
    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, dag FROM script_versions"))
    for row in rows:
        dag_hash = hashlib.sha256(
            json.dumps(row.dag, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        conn.execute(
            text("UPDATE script_versions SET dag_hash = :h WHERE id = :id"),
            {"h": dag_hash, "id": row.id}
        )
    op.alter_column("script_versions", "dag_hash", nullable=False)
    op.create_index("ix_script_versions_dag_hash", "script_versions", ["dag_hash"])
```

---

## 3. Протокол EXECUTE_DAG v2

### 3.1 Облегчённая команда (кеш-хит)

```json
{
    "command_id": "ce44ef91-...",
    "type": "EXECUTE_DAG",
    "signed_at": 1740700000,
    "ttl_seconds": 300,
    "payload": {
        "task_id": "ce44ef91-...",
        "dag_hash": "a3f2b8c1d4e5f6...64_chars",
        "dag_size": 23456,
        "timeout_ms": 86400000
    }
}
```

**Размер команды:** ~250 байт вместо ~40 000 байт.

### 3.2 Полная команда (fallback / первый запуск)

```json
{
    "command_id": "ce44ef91-...",
    "type": "EXECUTE_DAG",
    "signed_at": 1740700000,
    "ttl_seconds": 300,
    "payload": {
        "task_id": "ce44ef91-...",
        "dag_hash": "a3f2b8c1d4e5f6...64_chars",
        "dag_size": 23456,
        "dag": { ... полный DAG ... },
        "timeout_ms": 86400000
    }
}
```

### 3.3 Запрос DAG агентом (кеш-промах)

```json
// Agent → Backend
{
    "type": "request_dag",
    "dag_hash": "a3f2b8c1d4e5f6...64_chars",
    "command_id": "ce44ef91-..."
}

// Backend → Agent
{
    "type": "dag_payload",
    "dag_hash": "a3f2b8c1d4e5f6...64_chars",
    "dag": { ... полный DAG ... },
    "command_id": "ce44ef91-..."
}
```

---

## 4. Реализация: Android-агент

### 4.1 DagCache — файловый кеш

```kotlin
/**
 * DagCache — Content-Addressable кеш DAG-скриптов.
 *
 * Хранилище: /data/data/<pkg>/files/dag_cache/<hash>.json
 * Индекс: EncryptedSharedPreferences (hash → metadata)
 * Лимит: 50 MB или 100 записей (LRU eviction)
 * Целостность: SHA-256 верификация при чтении
 */
@Singleton
class DagCache @Inject constructor(
    @ApplicationContext private val context: Context,
    private val prefs: EncryptedSharedPreferences,
) {
    companion object {
        private const val CACHE_DIR = "dag_cache"
        private const val MAX_ENTRIES = 100
        private const val MAX_SIZE_BYTES = 50L * 1024 * 1024  // 50 MB
        private const val INDEX_KEY = "dag_cache_index"
    }

    private val cacheDir: File by lazy {
        File(context.filesDir, CACHE_DIR).also { it.mkdirs() }
    }
    
    private val json = Json { ignoreUnknownKeys = true }

    /**
     * Проверить наличие DAG в кеше по хешу.
     * O(1) — проверка файла + SHA-256 верификация.
     */
    fun has(dagHash: String): Boolean {
        val file = File(cacheDir, "$dagHash.json")
        if (!file.exists()) return false
        // Верификация целостности
        val actualHash = computeSha256(file.readBytes())
        if (actualHash != dagHash) {
            Timber.w("[DagCache] Integrity check failed for $dagHash, removing")
            file.delete()
            removeFromIndex(dagHash)
            return false
        }
        // Обновить LRU timestamp
        touchInIndex(dagHash)
        return true
    }

    /**
     * Получить DAG из кеша. 
     * @return JsonObject или null если не найден/повреждён.
     */
    fun get(dagHash: String): JsonObject? {
        if (!has(dagHash)) return null
        return try {
            val file = File(cacheDir, "$dagHash.json")
            json.parseToJsonElement(file.readText()).jsonObject
        } catch (e: Exception) {
            Timber.w(e, "[DagCache] Error reading $dagHash")
            File(cacheDir, "$dagHash.json").delete()
            removeFromIndex(dagHash)
            null
        }
    }

    /**
     * Положить DAG в кеш. Перезаписывает если уже есть.
     * Автоматическая LRU eviction при превышении лимита.
     */
    fun put(dagHash: String, dag: JsonObject) {
        evictIfNeeded()
        val canonical = json.encodeToString(dag)
        // Проверяем что хеш совпадает с содержимым
        val actualHash = computeSha256(canonical.toByteArray())
        require(actualHash == dagHash) {
            "DAG hash mismatch: expected=$dagHash actual=$actualHash"
        }
        File(cacheDir, "$dagHash.json").writeText(canonical)
        addToIndex(dagHash, canonical.length.toLong())
        Timber.d("[DagCache] Stored $dagHash (${canonical.length} bytes)")
    }

    /**
     * LRU eviction: удаляем самые старые записи пока не уложимся в лимиты.
     */
    private fun evictIfNeeded() {
        val index = getIndex()
        var totalSize = index.values.sumOf { it.size }
        val sorted = index.entries.sortedBy { it.value.lastAccessedAt }
        
        val toRemove = mutableListOf<String>()
        for (entry in sorted) {
            if (index.size - toRemove.size <= MAX_ENTRIES && totalSize <= MAX_SIZE_BYTES) break
            toRemove.add(entry.key)
            totalSize -= entry.value.size
        }
        
        for (hash in toRemove) {
            File(cacheDir, "$hash.json").delete()
            Timber.d("[DagCache] Evicted $hash (LRU)")
        }
        if (toRemove.isNotEmpty()) saveIndex(index - toRemove.toSet())
    }

    private fun computeSha256(data: ByteArray): String {
        val digest = java.security.MessageDigest.getInstance("SHA-256")
        return digest.digest(data).joinToString("") { "%02x".format(it) }
    }
}
```

### 4.2 Модификация CommandDispatcher

```kotlin
CommandType.EXECUTE_DAG -> {
    val payload = cmd.payload
    val dagHash = payload["dag_hash"]?.jsonPrimitive?.contentOrNull
    val inlineDag = payload["dag"]?.jsonObject
    val timeoutMs = payload["timeout_ms"]?.jsonPrimitive?.longOrNull ?: 3_600_000L

    // 1. Попытка взять из кеша
    val dag = when {
        inlineDag != null -> {
            // DAG передан inline — положить в кеш
            if (dagHash != null) dagCache.put(dagHash, inlineDag)
            inlineDag
        }
        dagHash != null && dagCache.has(dagHash) -> {
            // Кеш-хит!
            Timber.i("[CMD] DAG cache hit: $dagHash")
            dagCache.get(dagHash)!!
        }
        dagHash != null -> {
            // Кеш-промах — запросить у бэкенда
            Timber.i("[CMD] DAG cache miss: $dagHash, requesting...")
            val downloaded = requestDag(dagHash, cmd.command_id)
                ?: throw RuntimeException("Failed to download DAG: $dagHash")
            dagCache.put(dagHash, downloaded)
            downloaded
        }
        else -> throw IllegalArgumentException("EXECUTE_DAG: no dag or dag_hash in payload")
    }

    dagMutex.withLock {
        dagRunner.execute(cmd.command_id, dag)
    }
}

/**
 * Запросить DAG у бэкенда через WebSocket и дождаться ответа.
 */
private suspend fun requestDag(
    dagHash: String,
    commandId: String,
): JsonObject? = withTimeout(30_000L) {
    val latch = CompletableDeferred<JsonObject>()
    pendingDagRequests[dagHash] = latch
    
    wsClient.sendJson(buildJsonObject {
        put("type", "request_dag")
        put("dag_hash", dagHash)
        put("command_id", commandId)
    })
    
    try {
        latch.await()
    } finally {
        pendingDagRequests.remove(dagHash)
    }
}
```

---

## 5. Реализация: Backend

### 5.1 Модификация dispatch_pending_tasks

```python
async def dispatch_pending_tasks(self) -> None:
    # ... существующий код ...
    
    # Формируем команду с dag_hash
    dag = version.dag
    dag_hash = compute_dag_hash(dag)
    
    command = {
        "command_id": task_id_str,
        "type": "EXECUTE_DAG",
        "signed_at": int(datetime.now(timezone.utc).timestamp()),
        "ttl_seconds": task.timeout_seconds,
        "payload": {
            "task_id": task_id_str,
            "dag_hash": dag_hash,
            "dag_size": len(json.dumps(dag)),
            "timeout_ms": task.timeout_seconds * 1000,
            # DAG inline — только при первом запуске или force
            # В будущем: убрать dag из payload когда агент подтвердит кеш
        },
    }
    
    # Оптимизация: если агент уже имеет этот DAG — не отправлять inline
    agent_cache_hashes = await self._get_agent_cache_hashes(device_id_str)
    if dag_hash not in agent_cache_hashes:
        command["payload"]["dag"] = dag  # Inline только при кеш-промахе
```

### 5.2 Обработка request_dag от агента

```python
# backend/api/ws/android/router.py
elif msg_type == "request_dag":
    dag_hash = msg.get("dag_hash")
    command_id = msg.get("command_id")
    
    # Найти DAG по хешу в БД
    version = await db.scalar(
        select(ScriptVersion).where(ScriptVersion.dag_hash == dag_hash)
    )
    if version:
        await ws.send_json({
            "type": "dag_payload",
            "dag_hash": dag_hash,
            "dag": version.dag,
            "command_id": command_id,
        })
    else:
        await ws.send_json({
            "type": "dag_payload",
            "dag_hash": dag_hash,
            "error": "DAG not found",
            "command_id": command_id,
        })
```

### 5.3 REST endpoint для скачивания DAG (HTTP fallback)

```python
@router.get("/scripts/dag/{dag_hash}")
async def get_dag_by_hash(
    dag_hash: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить DAG по Content-Addressable hash.
    Может использоваться агентом как HTTP fallback если WS недоступен.
    """
    version = await db.scalar(
        select(ScriptVersion)
        .where(ScriptVersion.dag_hash == dag_hash)
        .where(ScriptVersion.org_id == current_user.org_id)
    )
    if not version:
        raise HTTPException(404, "DAG not found")
    return {"dag_hash": dag_hash, "dag": version.dag}
```

---

## 6. Безопасность

### 6.1 Tamper detection

SHA-256 вычисляется на бэкенде при создании ScriptVersion. Агент верифицирует хеш при каждом чтении из кеша.

### 6.2 Cache poisoning protection

- Кеш хранится в internal storage (`/data/data/<pkg>/files/`) — недоступен другим приложениям
- Каждый read проверяет `SHA-256(content) == filename`
- При несовпадении: удаление + re-download

### 6.3 Лимиты

- **MAX_ENTRIES = 100** — не больше 100 скриптов в кеше (LRU eviction)
- **MAX_SIZE = 50 MB** — суммарный лимит
- **Один файл: max 1 MB** — защита от аномально больших DAG

---

## 7. Метрики кеширования

### 7.1 Телеметрия от агента

```json
{
    "type": "telemetry",
    "dag_cache": {
        "entries": 42,
        "total_size_kb": 1230,
        "hit_rate_percent": 94.5,
        "hits": 189,
        "misses": 11
    }
}
```

### 7.2 Dashboard метрика

```
sphere_dag_cache_hit_rate{device_id="..."} 0.945
sphere_dag_cache_entries{device_id="..."} 42
sphere_dag_cache_size_bytes{device_id="..."} 1259520
```

---

## 8. Таблица изменений

| Компонент | Файл | Что менять |
|-----------|------|-----------|
| Backend | `models/script.py` | + dag_hash: String(64), indexed |
| Backend | `services/script_service.py` | compute_dag_hash() при создании версии |
| Backend | `services/task_service.py` | Отправка dag_hash вместо full DAG |
| Backend | `api/ws/android/router.py` | Обработка request_dag |
| Backend | `api/v1/scripts/router.py` | GET /scripts/dag/{hash} |
| Backend | `alembic/versions/` | Миграция: add dag_hash + backfill |
| Android | `DagCache.kt` | NEW: Content-Addressable файловый кеш |
| Android | `CommandDispatcher.kt` | Cache-first в EXECUTE_DAG handler |
| Android | `SphereWebSocketClient.kt` | Обработка dag_payload ответа |

---

## 9. Критерии готовности

- [ ] SHA-256 вычисляется при создании ScriptVersion
- [ ] dag_hash indexed в PostgreSQL
- [ ] Команда EXECUTE_DAG содержит dag_hash
- [ ] Агент проверяет кеш перед запуском
- [ ] Кеш-промах → запрос через WS → получение DAG → сохранение
- [ ] LRU eviction при превышении 100 записей / 50 MB
- [ ] Integrity check (SHA-256 verification) при каждом чтении
- [ ] HTTP fallback endpoint для скачивания DAG
- [ ] Телеметрия: hit_rate, entries, size
- [ ] Обратная совместимость: inline DAG по-прежнему работает
- [ ] Тесты: DagCache unit tests, hash computation roundtrip
