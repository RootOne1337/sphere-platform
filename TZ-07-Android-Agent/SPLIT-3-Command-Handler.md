# SPLIT-3 — Command Handler (DAG Dispatch)

**ТЗ-родитель:** TZ-07-Android-Agent  
**Ветка:** `stage/7-android`  
**Задача:** `SPHERE-038`  
**Исполнитель:** Android  
**Оценка:** 1.5 дня  
**Блокирует:** TZ-07 SPLIT-4 (Lua Engine)

---

## Цель Сплита

Принимать команды сервера, выполнять примитивные adb-действия и запускать DAG-скрипты с отправкой статусов и результатов.

---

## Шаг 1 — CommandType и IncomingCommand

```kotlin
// AndroidAgent/command/model/CommandType.kt
enum class CommandType {
    // Управление устройством
    WAKE_SCREEN, LOCK_SCREEN, REBOOT, SHELL,
    // ADB-примитивы
    TAP, SWIPE, TYPE_TEXT, KEY_EVENT, SCREENSHOT,
    // DAG-скрипт
    EXECUTE_DAG,
    // VPN
    VPN_CONNECT, VPN_DISCONNECT, VPN_RECONNECT,
    // OTA обновления (реализация в SPLIT-5)
    OTA_UPDATE,
    // Агент
    PING, UPDATE_CONFIG, REQUEST_STATUS,
}

// AndroidAgent/command/model/IncomingCommand.kt
@Serializable
data class IncomingCommand(
    val command_id: String,
    val type: CommandType,
    val payload: JsonObject = JsonObject(emptyMap()),
    val signed_at: Long,  // UTC epoch seconds
    val ttl_seconds: Int = 60,
)

@Serializable
data class CommandAck(
    val command_id: String,
    val status: String,  // "received" | "running" | "completed" | "failed"
    val error: String? = null,
    val result: JsonObject? = null,
)
```

---

## Шаг 2 — CommandDispatcher

```kotlin
// AndroidAgent/command/CommandDispatcher.kt
@Singleton
class CommandDispatcher @Inject constructor(
    private val wsClient: SphereWebSocketClient,
    private val adbActions: AdbActionExecutor,
    private val dagRunner: DagRunner,
    private val vpnManager: SphereVpnManager,
    private val scope: CoroutineScope,
) {
    private val json = Json { ignoreUnknownKeys = true }
    
    fun start() {
        wsClient.onJsonMessage = { msg ->
            // FIX ARCH-4: Ping/pong обрабатываем НЕМЕДЛЕННО в потоке колбэка,
            // НЕ через scope.launch. Иначе DagRunner заблокирует Dispatchers.IO,
            // pong не уйдёт, и сервер убьёт соединение через 45с (TZ-03 SPLIT-4:60).
            if (msg["type"]?.jsonPrimitive?.contentOrNull == "ping") {
                handlePingImmediate(msg)
            } else {
                scope.launch { handleMessage(msg) }
            }
        }
    }
    
    /**
     * Обрабатывает ping синхронно — не зависит от корутинного пула.
     * Критично для DAG длиннее 45с: DagRunner блокирует IO-потоки,
     * но pong ДОЛЖЕН уйти в рамках heartbeat timeout.
     */
    private fun handlePingImmediate(msg: JsonObject) {
        wsClient.sendJson(buildJsonObject {
            put("type", "pong")
            put("ts", msg["ts"]?.jsonPrimitive?.doubleOrNull ?: 0.0)
            with(deviceStatusProvider) {
                put("battery", getBatteryLevel())
                put("cpu", getCpuUsage())
                put("ram_mb", getRamUsageMb())
                put("screen_on", isScreenOn())
                put("vpn_active", isVpnActive())
            }
        })
    }
    
    private suspend fun handleMessage(msg: JsonObject) {
        // Пинг от сервера — формат {"type": "ping", "ts": 1234567890.123}
        // ВАЖНО: сервер шлёт {"type": "ping"}, НЕ {"ping": ...}
        if (msg["type"]?.jsonPrimitive?.contentOrNull == "ping") {
            wsClient.sendJson(buildJsonObject {
                put("type", "pong")
                put("ts", msg["ts"]?.jsonPrimitive?.doubleOrNull ?: 0.0)
                // Телеметрия в pong — экономит отдельные сообщения
                with(deviceStatusProvider) {
                    put("battery", getBatteryLevel())
                    put("cpu", getCpuUsage())
                    put("ram_mb", getRamUsageMb())
                    put("screen_on", isScreenOn())
                    put("vpn_active", isVpnActive())
                }
            })
            return
        }
        
        val cmd = try {
            json.decodeFromJsonElement<IncomingCommand>(JsonElement(msg))
        } catch (e: Exception) {
            Timber.w("Cannot parse command: ${e.message}")
            return
        }
        
        // TTL check — отбросить устаревшие
        val ageSeconds = System.currentTimeMillis() / 1000 - cmd.signed_at
        if (ageSeconds > cmd.ttl_seconds) {
            Timber.w("[${cmd.command_id}] Expired command (age=${ageSeconds}s), skipping")
            ack(cmd.command_id, "failed", "expired")
            return
        }
        
        ack(cmd.command_id, "received")
        
        val result = runCatching {
            ack(cmd.command_id, "running")
            dispatch(cmd)
        }
        
        if (result.isSuccess) {
            ack(cmd.command_id, "completed", result = result.getOrNull())
        } else {
            val err = result.exceptionOrNull()?.message ?: "unknown"
            Timber.e(result.exceptionOrNull(), "[${cmd.command_id}] Failed")
            ack(cmd.command_id, "failed", err)
        }
    }
    
    private suspend fun dispatch(cmd: IncomingCommand): JsonObject? {
        return when (cmd.type) {
            CommandType.PING -> buildJsonObject { put("pong", true) }
            CommandType.TAP -> {
                val x = cmd.payload["x"]!!.jsonPrimitive.int
                val y = cmd.payload["y"]!!.jsonPrimitive.int
                adbActions.tap(x, y)
                null
            }
            CommandType.SWIPE -> {
                val x1 = cmd.payload["x1"]!!.jsonPrimitive.int
                val y1 = cmd.payload["y1"]!!.jsonPrimitive.int
                val x2 = cmd.payload["x2"]!!.jsonPrimitive.int
                val y2 = cmd.payload["y2"]!!.jsonPrimitive.int
                val duration = cmd.payload["duration_ms"]?.jsonPrimitive?.int ?: 300
                adbActions.swipe(x1, y1, x2, y2, duration)
                null
            }
            CommandType.TYPE_TEXT -> {
                val text = cmd.payload["text"]!!.jsonPrimitive.content
                adbActions.typeText(text)
                null
            }
            CommandType.KEY_EVENT -> {
                val keyCode = cmd.payload["key_code"]!!.jsonPrimitive.int
                adbActions.keyEvent(keyCode)
                null
            }
            CommandType.SCREENSHOT -> {
                val path = adbActions.takeScreenshot()
                buildJsonObject { put("path", path) }
            }
            CommandType.EXECUTE_DAG -> {
                val dagJson = cmd.payload["dag"]!!.jsonObject
                dagRunner.execute(cmd.command_id, dagJson)
            }
            CommandType.VPN_CONNECT -> {
                val config = cmd.payload["config"]!!.jsonPrimitive.content
                vpnManager.connect(config)
                null
            }
            CommandType.VPN_DISCONNECT -> { vpnManager.disconnect(); null }
            CommandType.VPN_RECONNECT -> { vpnManager.reconnect(); null }
            CommandType.SHELL -> {
                val command = cmd.payload["cmd"]!!.jsonPrimitive.content
                // Только если KernelSU root доступен
                val output = adbActions.shell(command)
                buildJsonObject { put("output", output) }
            }
            CommandType.OTA_UPDATE -> {
                // Реализация в TZ-07 SPLIT-5 (OtaUpdateService)
                // При интеграции: otaUpdateService.performUpdate(payload)
                throw UnsupportedOperationException("OTA_UPDATE handled in SPLIT-5")
            }
            else -> {
                Timber.w("Unhandled command type: ${cmd.type}")
                null
            }
        }
    }
    
    private fun ack(commandId: String, status: String, error: String? = null, result: JsonObject? = null) {
        val ack = CommandAck(commandId, status, error, result)
        wsClient.sendJson(json.encodeToJsonElement(ack).jsonObject)
    }
}
```

---

## Шаг 3 — AdbActionExecutor

```kotlin
// AndroidAgent/command/AdbActionExecutor.kt
@Singleton
class AdbActionExecutor @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        // БЕЗОПАСНОСТЬ: allowlist для предотвращения shell injection.
        // Запрещаем: ; | & $ ` ( ) { } < > \ ! # ~ и переводы строк.
        // Аналогично PC Agent TZ-08 SPLIT-4 AdbBridgeService.shell().
        private val SHELL_INJECTION_PATTERN = Regex("""[;|&$`(){}\\\\<>!\n\r#~]""".trimIndent())
    }
    
    // ─── FIX 7.3: ИНТЕРАКТИВНАЯ ROOT-СЕССИЯ ───────────────────────────
    // БЫЛО: Runtime.getRuntime().exec(arrayOf("su", "-c", "input tap $x $y")).waitFor()
    //   → КАЖДЫЙ вызов = fork() + exec() + waitpid() = 50-150ms overhead
    //   → При 5 тап/с в скрипте автоматизации: 100% CPU, system interrupts
    //
    // СТАЛО: Один открытый Process("su") + DataOutputStream
    //   → Команды пишутся в stdin (< 1ms)
    //   → Экономия ~99% CPU на вводе команд
    // ──────────────────────────────────────────────────────────────────
    
    private val rootProcess: Process by lazy {
        Runtime.getRuntime().exec("su").also {
            Timber.i("Root session opened")
        }
    }
    
    private val rootStream: DataOutputStream by lazy {
        DataOutputStream(rootProcess.outputStream)
    }
    
    /**
     * Выполнить команду в постоянной root-сессии.
     * synchronized — защита от конкурентного доступа из разных корутин.
     */
    private fun executeRootCommand(cmd: String) {
        synchronized(rootStream) {
            rootStream.writeBytes("$cmd\n")
            rootStream.flush()
        }
    }
    
    /**
     * Безопасное закрытие root-сессии при уничтожении сервиса.
     */
    fun closeRootSession() {
        try {
            synchronized(rootStream) {
                rootStream.writeBytes("exit\n")
                rootStream.flush()
            }
            rootProcess.waitFor(5, TimeUnit.SECONDS)
            rootProcess.destroyForcibly()
            Timber.i("Root session closed")
        } catch (e: Exception) {
            Timber.w(e, "Error closing root session")
        }
    }
    
    fun tap(x: Int, y: Int) {
        executeRootCommand("input tap $x $y")
    }
    
    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Int) {
        executeRootCommand("input swipe $x1 $y1 $x2 $y2 $durationMs")
    }
    
    fun typeText(text: String) {
        // Escape spaces для ADB input
        val escaped = text.replace(" ", "%s")
        executeRootCommand("input text $escaped")
    }
    
    fun keyEvent(keyCode: Int) {
        executeRootCommand("input keyevent $keyCode")
    }
    
    suspend fun takeScreenshot(): String {
        val path = "/sdcard/sphere_screenshot_${System.currentTimeMillis()}.png"
        withContext(Dispatchers.IO) {
            executeRootCommand("screencap -p $path")
            // Ждём завершения записи файла (screencap не блокирует stdin)
            delay(200)
        }
        return path
    }
    
    suspend fun shell(command: String): String {
        // БЕЗОПАСНОСТЬ: проверяем перед передачей в su -c
        require(!SHELL_INJECTION_PATTERN.containsMatchIn(command)) {
            "Shell injection: forbidden metacharacters in command"
        }
        require(command.all { it.code in 32..126 }) {
            "Non-printable characters in shell command"
        }
        // shell() по-прежнему через отдельный процесс — нужен stdout
        return withContext(Dispatchers.IO) {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
            process.inputStream.bufferedReader().readText()
        }
    }
}
```

---

## Шаг 4 — DagRunner (stub, полная реализация в SPLIT-4)

```kotlin
// AndroidAgent/command/DagRunner.kt
@Singleton
class DagRunner @Inject constructor(
    private val luaEngine: LuaEngine,       // TZ-07 SPLIT-4
    private val adbActions: AdbActionExecutor,
    private val wsClient: SphereWebSocketClient,  // FIX ARCH-1: для прогресса
    private val prefs: EncryptedSharedPreferences, // FIX ARCH-2: pending results
) {
    private val json = Json { ignoreUnknownKeys = true }
    
    suspend fun execute(commandId: String, dagJson: JsonObject): JsonObject {
        val startNodeId = dagJson["entry_node"]!!.jsonPrimitive.content
        val nodes = dagJson["nodes"]!!.jsonObject
        
        val results = mutableMapOf<String, Any?>()
        var currentNodeId: String? = startNodeId
        
        while (currentNodeId != null) {
            val node = nodes[currentNodeId]?.jsonObject
                ?: throw IllegalArgumentException("Node $currentNodeId not found")
            
            val nodeType = node["type"]!!.jsonPrimitive.content
            val result = executeNode(nodeType, node, results)
            results[currentNodeId] = result
            
            // ─── FIX ARCH-1: Промежуточный прогресс ────────────────────
            // БЫЛО: агент шлёт ACK только в конце (completed/failed)
            // → DAG из 50 нод = 10 минут тишины → дашборд не видит прогресс
            // → сервер может решить что агент мёртв
            //
            // СТАЛО: task_progress после каждого узла
            if (wsClient.isConnected) {
                wsClient.sendJson(buildJsonObject {
                    put("type", "task_progress")
                    put("task_id", commandId)
                    put("current_node", currentNodeId)
                    put("nodes_done", results.size)
                    put("total_nodes", nodes.size)
                })
            }
            // ────────────────────────────────────────────────────────────
            
            // Next node — берём из links или из ветки условия
            currentNodeId = resolveNextNode(nodeType, node, result)
        }
        
        val finalResult = buildJsonObject {
            put("nodes_executed", results.size)
            put("success", true)
        }
        
        // ─── FIX ARCH-2: Сохранить результат при потере WS ─────────
        // Если WS упал посреди DAG — результат сохраняем локально.
        // При reconnect — flushPendingResults() отправит накопленное.
        if (!wsClient.isConnected) {
            savePendingResult(commandId, finalResult)
        }
        // ────────────────────────────────────────────────────────────
        
        return finalResult
    }
    
    /**
     * FIX ARCH-2: Сохранить результат DAG в SharedPreferences.
     * Вызывается когда WS недоступен — результат не потеряется.
     */
    private fun savePendingResult(commandId: String, result: JsonObject) {
        val pending = prefs.getStringSet("pending_dag_results", mutableSetOf())
            ?.toMutableSet() ?: mutableSetOf()
        pending.add(json.encodeToString(buildJsonObject {
            put("command_id", commandId)
            put("result", result)
            put("saved_at", System.currentTimeMillis())
        }))
        prefs.edit().putStringSet("pending_dag_results", pending).apply()
        Timber.i("[DAG] Результат сохранён локально, command=$commandId")
    }
    
    /**
     * FIX ARCH-2: Отправить накопленные результаты при reconnect.
     * Вызывается из SphereWebSocketClient.onConnected callback.
     */
    suspend fun flushPendingResults() {
        val pending = prefs.getStringSet("pending_dag_results", emptySet())
            ?.toList() ?: return
        if (pending.isEmpty()) return
        
        Timber.i("[DAG] Отправка ${pending.size} отложенных результатов")
        for (entry in pending) {
            try {
                val obj = json.parseToJsonElement(entry).jsonObject
                val cmdId = obj["command_id"]!!.jsonPrimitive.content
                val result = obj["result"]!!.jsonObject
                wsClient.sendJson(buildJsonObject {
                    put("command_id", cmdId)
                    put("status", "completed")
                    put("result", result)
                })
            } catch (e: Exception) {
                Timber.w(e, "[DAG] Ошибка flush pending result")
            }
        }
        prefs.edit().remove("pending_dag_results").apply()
    }
    
    private suspend fun executeNode(
        type: String,
        node: JsonObject,
        ctx: Map<String, Any?>,
    ): Any? {
        return when (type) {
            "Tap" -> {
                val x = node["x"]!!.jsonPrimitive.int
                val y = node["y"]!!.jsonPrimitive.int
                adbActions.tap(x, y)
                null
            }
            "Sleep" -> {
                val ms = node["duration_ms"]!!.jsonPrimitive.long
                delay(ms)
                null
            }
            "Lua" -> {
                val code = node["code"]!!.jsonPrimitive.content
                luaEngine.execute(code, ctx)
            }
            "End" -> null
            else -> throw UnsupportedOperationException("Node type $type not implemented")
        }
    }
    
    private fun resolveNextNode(type: String, node: JsonObject, result: Any?): String? {
        if (type == "Condition") {
            val branch = if (result as? Boolean == true) "true_branch" else "false_branch"
            return node["links"]?.jsonObject?.get(branch)?.jsonPrimitive?.content
        }
        return node["links"]?.jsonObject?.get("next")?.jsonPrimitive?.content
    }
}
```

---

## Критерии готовности

- [ ] TTL check: команда старше ttl_seconds — ack "failed"+"expired" и не выполняется
- [ ] ACK sequence: received → running → completed/failed
- [ ] TAP/SWIPE/TYPE_TEXT/KEY_EVENT через `su -c input ...`
- [ ] SHELL: команды проходят через SHELL_INJECTION_PATTERN + `isInRange(32..126)` — `; | & $ \`` и др. → exception
- [ ] EXECUTE_DAG делегирует в DagRunner, возвращает nodes_executed
- [ ] Неизвестный тип команды — warning в лог, не краш
- [ ] Binary WebSocket сообщения не падают (onBinaryMessage просто игнорируется или передаётся)
