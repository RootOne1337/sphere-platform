package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.lua.LuaEngine
import com.sphereplatform.agent.ws.SphereWebSocketClient
import com.sphereplatform.agent.lua.executeWithTimeout
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * DagRunner — исполняет DAG-скрипты команд.
 *
 * ## DAG JSON Contract (TZ-04 SPLIT-1 MERGE-3)
 * - `nodes` — **array** (не map) объектов Node
 * - Каждый Node: `id`, `action.type`, `on_success`, `on_failure`, `retry`, `timeout_ms`
 * - `action.type` — lowercase. Базовые: "tap", "swipe", "type_text", "sleep", "key_event",
 *   "screenshot", "lua", "find_element", "condition", "launch_app", "stop_app".
 *   Жесты: "long_press", "double_tap", "scroll", "scroll_to".
 *   Ожидание: "wait_for_element_gone".
 *   Элементы: "tap_element", "find_first_element", "tap_first_visible", "get_element_text", "input_clear".
 *   Переменные: "set_variable", "get_variable".
 *   Сеть: "http_request".
 *   Система: "open_url", "clear_app_data", "get_device_info", "shell".
 *   QA: "assert".
 *   Управление: "loop", "start", "end".
 *
 * ## Что реализовано
 * - Per-node retry с exponential backoff (50ms / 150ms / 450ms / …)
 * - Per-node timeout через withTimeout
 * - Global DAG timeout
 * - Подробные NodeExecutionLog (duration_ms, error, output) в финальном результате
 * - Realtime task_progress по WS после каждого узла
 * - Pending results в EncryptedSharedPreferences при потере WS
 */
@Singleton
class DagRunner @Inject constructor(
    private val luaEngine: LuaEngine,
    private val adbActions: AdbActionExecutor,
    private val wsClient: SphereWebSocketClient,
    private val prefs: EncryptedSharedPreferences,
    private val httpClient: okhttp3.OkHttpClient,
) {
    companion object {
        /** FIX AUDIT-3.3: Лимит нод в DAG — защита от OOM */
        private const val MAX_DAG_NODES = 500
        /** FIX AUDIT-3.6: Лимит pending results при offline */
        private const val MAX_PENDING_RESULTS = 50
        /** FIX H2: Максимальная глубина вложенности loop → executeNode. Защита от StackOverflow. */
        private const val MAX_EXECUTE_DEPTH = 10
        /** FIX H5: Макс размер HTTP response body в DAG http_request */
        private const val MAX_HTTP_RESPONSE_CHARS = 256 * 1024  // 256KB
        /**
         * FIX F5: Макс размер одного сериализованного pending result.
         * DAG с сотнями нод может сгенерировать огромный node_logs → раздувание
         * EncryptedSharedPreferences → долгие I/O при каждом commit().
         */
        private const val MAX_PENDING_RESULT_CHARS = 128 * 1024  // 128KB
        /**
         * PERF: Лимит записей в iterLogs внутри loop-ноды.
         * 1000 iterations × 10 body nodes = 10 000 log entries → при serialize
         * мегабайтный JSON → OOM на слабых эмуляторах (512MB heap).
         * 200 записей достаточно для диагностики любого loop.
         */
        private const val MAX_LOOP_LOGS = 200
        /**
         * PERF: Лимит hop'ов при маршрутизации on_success/on_failure.
         * Без него: node_A.on_failure → node_B.on_failure → node_A → бесконечный цикл,
         * 100% CPU, DAG никогда не завершится. 500 hop'ов = 500-узловой DAG × 1 проход.
         * При циклических DAG (29 нод × ~17 циклов) — достаточно для выполнения скрипта
         * в рамках типичного 5-мин таймаута, при этом защищает от бесконечного цикла.
         */
        private const val MAX_ROUTING_HOPS = 500
        /**
         * PERF: Макс длина output.toString() в node_logs.
         * Без лимита: http_request body 256KB × 50 нод = 12.8MB в node_logs JSON.
         */
        private const val MAX_LOG_OUTPUT_CHARS = 2048
    }

    private val json = Json { ignoreUnknownKeys = true }

    @Volatile
    private var cancelRequested = false

    /** Called from CommandDispatcher when CANCEL_DAG arrives. */
    fun requestCancel() {
        cancelRequested = true
        Timber.i("[DAG] Cancel requested by user")
    }

    @Volatile
    private var pauseRequested = false

    /**
     * Ставит текущий DAG на паузу: выполнение нод прерывается между шагами
     * и возобновляется только при вызове [requestResume] или [requestCancel].
     * Called from CommandDispatcher when PAUSE_DAG arrives.
     */
    fun requestPause() {
        pauseRequested = true
        Timber.i("[DAG] Pause requested by user")
    }

    /**
     * Снимает DAG с паузы — выполнение продолжается с той ноды, на которой остановились.
     * Called from CommandDispatcher when RESUME_DAG arrives.
     */
    fun requestResume() {
        pauseRequested = false
        Timber.i("[DAG] Resume requested by user")
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Исполняет DAG-скрипт.
     *
     * @param commandId  — уникальный ID команды/задачи (используется для progress/ack)
     * @param dagJson    — JSON-объект с DAG-описанием (entry_node, nodes, ...)
     * @param timeoutMs  — таймаут исполнения из payload (приоритетнее DAG-поля timeout_ms).
     *                     Без явного значения: берётся из dagJson["timeout_ms"] или 300_000ms (5 мин).
     */
    suspend fun execute(commandId: String, dagJson: JsonObject, timeoutMs: Long? = null): JsonObject {
        cancelRequested = false  // сброс при новом запуске
        pauseRequested  = false  // сброс при новом запуске

        val entryNodeId = dagJson["entry_node"]!!.jsonPrimitive.content
        val nodesArray = dagJson["nodes"]!!.jsonArray          // LIST, не map!
        // Приоритет: явный параметр → поле в DAG → дефолт 5 мин.
        // FIX: Ранее читался dagJson["timeout_ms"], но backend кладёт timeout_ms в payload,
        // а НЕ внутрь dag. Результат: всегда fallback на 3_600_000ms → DAG крутился 1 час
        // вместо 5 мин, блокируя dagMutex и не давая запуститься следующей задаче.
        val globalTimeoutMs = timeoutMs
            ?: dagJson["timeout_ms"]?.jsonPrimitive?.longOrNull
            ?: 300_000L

        // FIX AUDIT-3.3: Лимит нод — защита от OOM на слабом эмуляторе.
        // 500 нод достаточно для любого реального DAG-скрипта.
        require(nodesArray.size <= MAX_DAG_NODES) {
            "DAG слишком большой: ${nodesArray.size} нод (лимит: $MAX_DAG_NODES)"
        }

        // Build id → node object map for O(1) lookup
        val nodeMap: Map<String, JsonObject> = nodesArray.associate { el ->
            val obj = el.jsonObject
            obj["id"]!!.jsonPrimitive.content to obj
        }

        val nodeLogs = mutableListOf<JsonObject>()
        val ctx = mutableMapOf<String, Any?>()   // execution context passed to Lua

        var success = true
        var failedNode: String? = null

        var currentNodeId: String? = entryNodeId

        // PERF: Счётчик hop'ов маршрутизации — защита от зацикливания
        // on_success/on_failure. Без него: A→B→A = ∞ цикл, 100% CPU.
        var routingHops = 0

        try {
        withTimeout(globalTimeoutMs) {
            while (currentNodeId != null) {
                // PERF: Проверка лимита маршрутных переходов
                routingHops++
                if (routingHops > MAX_ROUTING_HOPS) {
                    Timber.e("[DAG] Routing hops exceeded $MAX_ROUTING_HOPS — возможен цикл, прерываем")
                    success = false
                    failedNode = currentNodeId
                    nodeLogs.add(makeLog(
                        currentNodeId ?: "unknown", "ROUTING_CYCLE", 0L, false,
                        "DAG routing exceeded $MAX_ROUTING_HOPS hops — probable cycle detected", null
                    ))
                    break
                }
                // ── Check for cancel request from backend ──────────────
                if (cancelRequested) {
                    Timber.i("[DAG] Cancelled by user at node '$currentNodeId'")
                    success = false
                    failedNode = currentNodeId
                    break
                }
                // ── Пауза: ждём снятия паузы или отмены ────────────────
                if (pauseRequested) {
                    Timber.i("[DAG] Paused at node '$currentNodeId' — waiting for resume")
                    while (pauseRequested) {
                        if (cancelRequested) break
                        delay(200L)
                    }
                    if (cancelRequested) {
                        Timber.i("[DAG] Cancelled during pause at node '$currentNodeId'")
                        success = false
                        failedNode = currentNodeId
                        break
                    }
                    Timber.i("[DAG] Resumed at node '$currentNodeId'")
                }
                val nodeId = currentNodeId ?: break
                val node = nodeMap[nodeId]
                    ?: throw IllegalArgumentException("Node '$nodeId' not found in DAG")

                val action = node["action"]!!.jsonObject
                val actionType = action["type"]!!.jsonPrimitive.content
                val retryMax = node["retry"]?.jsonPrimitive?.intOrNull ?: 0
                val rawTimeoutMs = node["timeout_ms"]?.jsonPrimitive?.longOrNull ?: 30_000L

                // Защита: для sleep-нод timeout должен быть >= action.ms + буфер
                val nodeTimeoutMs = if (actionType == "sleep") {
                    val sleepMs = action["ms"]?.jsonPrimitive?.longOrNull ?: 0L
                    maxOf(rawTimeoutMs, sleepMs + 3_000L)
                } else {
                    rawTimeoutMs
                }

                val onSuccess = node["on_success"]?.jsonPrimitive?.contentOrNull
                val onFailure = node["on_failure"]?.jsonPrimitive?.contentOrNull

                // stop node terminates loop
                if (actionType == "end" || actionType == "start") {
                    nodeLogs.add(makeLog(nodeId, actionType, 0L, true, null, null))
                    currentNodeId = onSuccess
                    continue
                }

                val startTs = System.currentTimeMillis()
                var nodeResult: Any? = null
                var nodeError: String? = null
                var nodeSuccess = false

                // Per-node retry loop with exponential backoff
                for (attempt in 0..retryMax) {
                    if (attempt > 0) {
                        val backoffMs = (50L * (1L shl (attempt - 1))).coerceAtMost(5_000L)
                        delay(backoffMs)
                        Timber.d("[DAG] Retry $attempt for node '$nodeId'")
                    }
                    try {
                        nodeResult = withTimeout(nodeTimeoutMs) {
                            executeNode(actionType, action, ctx)
                        }
                        nodeSuccess = true
                        nodeError = null
                        break
                    } catch (e: TimeoutCancellationException) {
                        nodeError = "timeout after ${nodeTimeoutMs}ms (attempt $attempt)"
                        Timber.w("[DAG] Node '$nodeId' timed out")
                        break   // no retry on timeout
                    } catch (e: kotlinx.coroutines.CancellationException) {
                        // Не глотаем отмену корутины (глобальный таймаут или cancel)
                        throw e
                    } catch (e: Exception) {
                        nodeError = e.message ?: "unknown error"
                        Timber.w(e, "[DAG] Node '$nodeId' failed attempt $attempt")
                    }
                }

                val durationMs = System.currentTimeMillis() - startTs
                nodeLogs.add(makeLog(nodeId, actionType, durationMs, nodeSuccess, nodeError, nodeResult))

                if (nodeSuccess) {
                    ctx[nodeId] = nodeResult
                } else {
                    success = false
                    failedNode = nodeId
                }

                // Realtime progress
                trySendProgress(commandId, nodeId, nodeLogs.size, nodeMap.size)

                // Route to next node
                currentNodeId = when {
                    actionType == "condition" -> {
                        // condition routes via action.on_true / action.on_false (TZ-04 SPLIT-1)
                        if (nodeResult as? Boolean == true)
                            action["on_true"]?.jsonPrimitive?.contentOrNull ?: onSuccess
                        else
                            action["on_false"]?.jsonPrimitive?.contentOrNull ?: onFailure
                    }
                    nodeSuccess -> onSuccess
                    else -> onFailure    // null = DAG stops
                }

                if (!nodeSuccess && onFailure == null) {
                    // No error handler configured — surface error to caller
                    throw RuntimeException("DAG failed at node '$nodeId': $nodeError")
                }
            }
        }
        } catch (e: TimeoutCancellationException) {
            // Глобальный таймаут DAG — не нодовый
            val elapsedSec = globalTimeoutMs / 1000
            Timber.w("[DAG] Global DAG timeout after ${elapsedSec}s at node '$currentNodeId'")
            success = false
            failedNode = currentNodeId
            nodeLogs.add(makeLog(
                currentNodeId ?: "unknown", "GLOBAL_TIMEOUT", globalTimeoutMs, false,
                "Global DAG timeout after ${elapsedSec}s (limit: ${elapsedSec}s)", null
            ))
        }

        val nodeLogsArray: JsonArray = buildJsonArray { nodeLogs.forEach { add(it) } }
        val finalResult = buildJsonObject {
            put("nodes_executed", nodeLogs.size)
            put("success", success)
            failedNode?.let { put("failed_node", it) }
            put("node_logs", nodeLogsArray)
        }

        if (!wsClient.isConnected) {
            savePendingResult(commandId, finalResult)
        }

        return finalResult
    }

    /**
     * Отправить накопленные результаты DAG при reconnect.
     * Вызывается из CommandDispatcher → wsClient.onConnected.
     */
    suspend fun flushPendingResults() {
        val pending = prefs.getStringSet("pending_dag_results", emptySet())
            ?.toList() ?: return
        if (pending.isEmpty()) return

        Timber.i("[DAG] Flushing ${pending.size} pending results")
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
                Timber.w(e, "[DAG] Error flushing pending result")
            }
        }
        prefs.edit().remove("pending_dag_results").apply()
    }

    // ── Node executor ─────────────────────────────────────────────────────────

    private suspend fun executeNode(
        type: String,
        action: JsonObject,
        ctx: MutableMap<String, Any?>,        depth: Int = 0,
    ): Any? {
        // FIX H2: Защита от глубокой рекурсии (loop внутри loop внутри loop...).
        // На слабых эмуляторах стек корутин ограничен — StackOverflowError → crash.
        require(depth < MAX_EXECUTE_DEPTH) {
            "DAG executeNode depth limit exceeded ($MAX_EXECUTE_DEPTH) — слишком глубокая вложенность loop"
        }
        return executeNodeInternal(type, action, ctx, depth)
    }

    private suspend fun executeNodeInternal(
        type: String,
        action: JsonObject,
        ctx: MutableMap<String, Any?>,
        depth: Int,    ): Any? = when (type) {

        "tap" -> {
            adbActions.tap(action["x"]!!.jsonPrimitive.int, action["y"]!!.jsonPrimitive.int)
            null
        }

        "swipe" -> {
            adbActions.swipe(
                action["x1"]!!.jsonPrimitive.int,
                action["y1"]!!.jsonPrimitive.int,
                action["x2"]!!.jsonPrimitive.int,
                action["y2"]!!.jsonPrimitive.int,
                action["duration_ms"]?.jsonPrimitive?.intOrNull ?: 300,
            )
            null
        }

        "type_text" -> {
            val text = action["text"]!!.jsonPrimitive.content
            val clearFirst = action["clear_first"]?.jsonPrimitive?.content?.toBoolean() ?: false
            if (clearFirst) {
                adbActions.keyEvent(277)  // KEYCODE_CTRL_A — select all
                delay(80)
                adbActions.keyEvent(67)   // KEYCODE_DEL — delete selection
                delay(80)
            }
            adbActions.typeText(text)
            null
        }

        "sleep" -> {
            delay(action["ms"]!!.jsonPrimitive.long)
            null
        }

        "key_event" -> {
            adbActions.keyEvent(action["keycode"]!!.jsonPrimitive.int)
            null
        }

        "screenshot" -> {
            val path = adbActions.takeScreenshot()
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            val result = mapOf("path" to path)
            if (key != null) ctx[key] = result
            result
        }

        "lua" -> {
            val code = action["code"]!!.jsonPrimitive.content
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            val result = luaEngine.executeWithTimeout(code, ctx)
            if (key != null) ctx[key] = result
            result
        }

        // Native condition checks (no Lua required)
        "condition" -> {
            val check = action["check"]?.jsonPrimitive?.contentOrNull
            val params = action["params"]?.jsonObject
            when (check) {
                "element_exists" -> {
                    val selector = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val strategy = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "text"
                    val timeoutMs = params?.get("timeout_ms")?.jsonPrimitive?.intOrNull ?: 5_000
                    adbActions.findElement(selector, strategy, timeoutMs) != null
                }
                "text_contains" -> {
                    val selector = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val text = params?.get("text")?.jsonPrimitive?.content ?: ""
                    val strategy = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "text"
                    val element = adbActions.findElement(selector, strategy, 5_000)
                    element != null && element.contains(text, ignoreCase = true)
                }
                "battery_above" -> {
                    // Can be read from shell without additional deps
                    val threshold = params?.get("level")?.jsonPrimitive?.intOrNull ?: 20
                    val level = adbActions.shell("cat /sys/class/power_supply/battery/capacity")
                        .trim().toIntOrNull() ?: 100
                    level > threshold
                }
                else -> {
                    // Fallback: Lua expression in "code" field
                    val code = action["code"]?.jsonPrimitive?.contentOrNull
                        ?: throw IllegalArgumentException("condition node has no 'check' or 'code'")
                    val result = luaEngine.executeWithTimeout(code, ctx)
                    result as? Boolean ?: (result != null && result != false)
                }
            }
        }

        "find_element" -> {
            val selector = action["selector"]!!.jsonPrimitive.content
            val strategy = action["strategy"]?.jsonPrimitive?.contentOrNull ?: "text"
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 10_000
            val failIfNotFound = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            val result = adbActions.findElement(selector, strategy, timeoutMs)
            if (result == null && failIfNotFound) {
                throw RuntimeException("Element not found: strategy=$strategy selector='$selector'")
            }
            if (key != null) ctx[key] = result
            result
        }

        // ── Multi-candidate element search (one dump per poll cycle) ──────────
        //
        // find_first_element — проверяет N кандидатов против одного XML-дампа.
        // Один uiautomator dump на итерацию, не N dumps. O(1 dump) вместо O(N dumps).
        //
        // Пример DAG action:
        // {
        //   "type": "find_first_element",
        //   "candidates": [
        //     { "selector": "//Button[@text='OK']",     "strategy": "xpath", "label": "ok" },
        //     { "selector": "//Button[@text='Accept']", "strategy": "xpath", "label": "accept" },
        //     { "selector": "close",                    "strategy": "text",  "label": "close" }
        //   ],
        //   "timeout_ms": 10000,
        //   "save_to": "found_btn",   // сохранить результат в ctx
        //   "fail_if_not_found": true
        // }
        // Результат в ctx["found_btn"]: { coords, selector, strategy, label, index }

        "find_first_element" -> {
            val candidates = action["candidates"]!!.jsonArray.mapIndexed { idx, el ->
                val obj      = el.jsonObject
                val selector = obj["selector"]!!.jsonPrimitive.content
                val strategy = obj["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
                val label    = obj["label"]?.jsonPrimitive?.contentOrNull ?: "candidate_$idx"
                AdbActionExecutor.SelectorCandidate(selector, strategy, label)
            }
            val timeoutMs      = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 10_000
            val failIfNotFound = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val key            = action["save_to"]?.jsonPrimitive?.contentOrNull

            val match = adbActions.findFirstElement(candidates, timeoutMs)
            if (match == null && failIfNotFound) {
                throw RuntimeException(
                    "find_first_element: none of ${candidates.size} candidates found within ${timeoutMs}ms"
                )
            }
            val result = match?.let {
                mapOf("coords" to it.coords, "selector" to it.selector,
                      "strategy" to it.strategy, "label" to it.label, "index" to it.index)
            }
            if (key != null) ctx[key] = result
            result
        }

        // tap_first_visible — find_first_element + tap в одном узле.
        // Самый частый паттерн: "вижу кнопку из набора — нажимаю", всё за один дамп.
        //
        // {
        //   "type": "tap_first_visible",
        //   "candidates": [ { "selector": "//Button[@text='OK']", "strategy": "xpath" }, ... ],
        //   "timeout_ms": 8000
        // }

        "tap_first_visible" -> {
            val candidates = action["candidates"]!!.jsonArray.mapIndexed { idx, el ->
                val obj      = el.jsonObject
                val selector = obj["selector"]!!.jsonPrimitive.content
                val strategy = obj["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
                val label    = obj["label"]?.jsonPrimitive?.contentOrNull ?: "candidate_$idx"
                AdbActionExecutor.SelectorCandidate(selector, strategy, label)
            }
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 8_000
            val failIfNotFound = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val match = adbActions.findFirstElement(candidates, timeoutMs)
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            if (match != null) {
                val parts = match.coords.split(",")
                // coords from uiautomator dump are already in physical pixels — use tapRaw
                adbActions.tapRaw(parts[0].toInt(), parts[1].toInt())
                val result = mapOf("tapped_label" to match.label, "tapped_index" to match.index, "coords" to match.coords)
                if (key != null) ctx[key] = result
                result
            } else if (failIfNotFound) {
                throw RuntimeException(
                    "tap_first_visible: none of ${candidates.size} candidates found within ${timeoutMs}ms"
                )
            } else {
                // Ни один кандидат не найден, но fail_if_not_found = false — возвращаем null (SUCCESS)
                Timber.d("[DAG] tap_first_visible: none of ${candidates.size} candidates found, continuing")
                null
            }
        }

        // ── App lifecycle ─────────────────────────────────────────────────────
        "launch_app" -> {
            val pkg = action["package"]!!.jsonPrimitive.content
            val delayMs = action["delay_ms"]?.jsonPrimitive?.longOrNull ?: 1_500L
            adbActions.launchApp(pkg)
            delay(delayMs)
            null
        }

        "stop_app" -> {
            val pkg = action["package"]!!.jsonPrimitive.content
            val delayMs = action["delay_ms"]?.jsonPrimitive?.longOrNull ?: 0L
            adbActions.stopApp(pkg)
            if (delayMs > 0) delay(delayMs)
            null
        }

        // ── Extended gestures ─────────────────────────────────────────────────

        "long_press" -> {
            val x = action["x"]!!.jsonPrimitive.int
            val y = action["y"]!!.jsonPrimitive.int
            val dur = action["duration_ms"]?.jsonPrimitive?.intOrNull ?: 800
            adbActions.longPress(x, y, dur)
            null
        }

        "double_tap" -> {
            val x = action["x"]!!.jsonPrimitive.int
            val y = action["y"]!!.jsonPrimitive.int
            adbActions.doubleTap(x, y)
            null
        }

        "scroll" -> {
            val dir = action["direction"]?.jsonPrimitive?.contentOrNull ?: "down"
            val pct = action["percent"]?.jsonPrimitive?.content?.toFloatOrNull() ?: 0.45f
            val dur = action["duration_ms"]?.jsonPrimitive?.intOrNull ?: 350
            adbActions.scroll(dir, pct, dur)
            null
        }

        "scroll_to" -> {
            val selector  = action["selector"]!!.jsonPrimitive.content
            val strategy  = action["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
            val dir       = action["direction"]?.jsonPrimitive?.contentOrNull ?: "down"
            val maxScrolls = action["max_scrolls"]?.jsonPrimitive?.intOrNull ?: 10
            val dur       = action["duration_ms"]?.jsonPrimitive?.intOrNull ?: 400
            val failIfNotFound = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val found = adbActions.scrollUntilVisible(selector, strategy, dir, maxScrolls, dur)
            if (!found && failIfNotFound) {
                throw RuntimeException("scroll_to: element not found after $maxScrolls scrolls: '$selector'")
            }
            found
        }

        "wait_for_element_gone" -> {
            val selector  = action["selector"]!!.jsonPrimitive.content
            val strategy  = action["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 15_000
            val failIfNotGone = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val gone = adbActions.waitForElementGone(selector, strategy, timeoutMs)
            if (!gone && failIfNotGone) {
                throw RuntimeException("wait_for_element_gone: element still visible after ${timeoutMs}ms")
            }
            gone
        }

        // ── Element helpers ────────────────────────────────────────────────────

        "tap_element" -> {
            val selector  = action["selector"]!!.jsonPrimitive.content
            val strategy  = action["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 8_000
            val failIfNotFound = action["fail_if_not_found"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            val coords = adbActions.findElement(selector, strategy, timeoutMs)
            if (coords == null) {
                if (failIfNotFound) throw RuntimeException("tap_element: element not found: '$selector'")
                null
            } else {
                val parts = coords.split(",")
                // coords from uiautomator dump are already in physical pixels — use tapRaw
                adbActions.tapRaw(parts[0].toInt(), parts[1].toInt())
                if (key != null) ctx[key] = coords
                coords
            }
        }

        "get_element_text" -> {
            val selector  = action["selector"]!!.jsonPrimitive.content
            val strategy  = action["strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 5_000
            val attribute = action["attribute"]?.jsonPrimitive?.contentOrNull ?: "text"
            val key       = action["save_to"]?.jsonPrimitive?.contentOrNull
            val text = adbActions.readElementText(selector, strategy, timeoutMs, attribute)
            if (key != null) ctx[key] = text
            text
        }

        "input_clear" -> {
            adbActions.keyEvent(277)   // KEYCODE_CTRL_A — select all
            delay(80)
            adbActions.keyEvent(67)    // KEYCODE_DEL — delete selection
            null
        }

        // ── Variables (server-driven context) ─────────────────────────────────

        "set_variable" -> {
            val key = action["key"]!!.jsonPrimitive.content
            val value: Any? = when {
                action.containsKey("value")            -> action["value"]!!.jsonPrimitive.content
                action.containsKey("from_node")        -> ctx[action["from_node"]!!.jsonPrimitive.content]
                action.containsKey("from_device_info") -> {
                    val infoKey = action["from_device_info"]!!.jsonPrimitive.content
                    adbActions.getDeviceInfo()[infoKey]
                }
                else -> null
            }
            ctx[key] = value
            value
        }

        "get_variable" -> {
            val key = action["key"]!!.jsonPrimitive.content
            ctx[key]
        }

        "increment_variable" -> {
            val key = action["key"]!!.jsonPrimitive.content
            val step = action["step"]?.jsonPrimitive?.intOrNull ?: 1
            val current = when (val v = ctx[key]) {
                is Number -> v.toInt()
                is String -> v.toIntOrNull() ?: 0
                else -> 0
            }
            val newVal = current + step
            ctx[key] = newVal.toString()
            newVal.toString()
        }

        // ── Network ───────────────────────────────────────────────────────────

        "http_request" -> {
            val url = action["url"]!!.jsonPrimitive.content
            require(url.startsWith("http://") || url.startsWith("https://")) {
                "http_request: only http/https schemes allowed"
            }
            val method    = action["method"]?.jsonPrimitive?.contentOrNull?.uppercase() ?: "GET"
            val body      = action["body"]?.jsonPrimitive?.contentOrNull
            val headers   = action["headers"]?.jsonObject
            val timeoutMs = action["timeout_ms"]?.jsonPrimitive?.intOrNull ?: 15_000
            val key       = action["save_to"]?.jsonPrimitive?.contentOrNull
            val result = performHttpRequest(url, method, body, headers, timeoutMs)
            if (key != null) ctx[key] = result["body"]
            result
        }

        // ── App / System extended ─────────────────────────────────────────────

        "open_url" -> {
            val url = action["url"]!!.jsonPrimitive.content
            val delayMs = action["delay_ms"]?.jsonPrimitive?.longOrNull ?: 1_000L
            adbActions.openUrl(url)
            if (delayMs > 0) delay(delayMs)
            null
        }

        "clear_app_data" -> {
            val pkg = action["package"]!!.jsonPrimitive.content
            val delayMs = action["delay_ms"]?.jsonPrimitive?.longOrNull ?: 500L
            adbActions.clearAppData(pkg)
            if (delayMs > 0) delay(delayMs)
            null
        }

        "get_device_info" -> {
            val info = adbActions.getDeviceInfo()
            val key = action["save_to"]?.jsonPrimitive?.contentOrNull
            if (key != null) ctx[key] = info
            info
        }

        "shell" -> {
            val command = action["command"]!!.jsonPrimitive.content
            val key     = action["save_to"]?.jsonPrimitive?.contentOrNull
            val failOnError = action["fail_on_error"]?.jsonPrimitive?.content?.toBoolean() ?: true
            val output = try {
                adbActions.shell(command)
            } catch (e: Exception) {
                if (failOnError) throw e
                Timber.d("[DAG] shell: command failed (fail_on_error=false): ${e.message}")
                ""
            }
            if (key != null) ctx[key] = output.trim()
            output
        }

        // ── QA / Assertions ───────────────────────────────────────────────────

        "assert" -> {
            val check   = action["check"]!!.jsonPrimitive.content
            val params  = action["params"]?.jsonObject
            val message = action["message"]?.jsonPrimitive?.contentOrNull ?: "Assertion failed: $check"
            val passed = when (check) {
                "element_exists" -> {
                    val sel   = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val strat = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "xpath"
                    val tms   = params?.get("timeout_ms")?.jsonPrimitive?.intOrNull ?: 5_000
                    adbActions.findElement(sel, strat, tms) != null
                }
                "element_gone" -> {
                    val sel   = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val strat = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "xpath"
                    val tms   = params?.get("timeout_ms")?.jsonPrimitive?.intOrNull ?: 5_000
                    adbActions.waitForElementGone(sel, strat, tms)
                }
                "text_equals" -> {
                    val sel      = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val strat    = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "id"
                    val expected = params?.get("value")?.jsonPrimitive?.content ?: ""
                    val tms      = params?.get("timeout_ms")?.jsonPrimitive?.intOrNull ?: 5_000
                    adbActions.readElementText(sel, strat, tms) == expected
                }
                "text_contains" -> {
                    val sel   = params?.get("selector")?.jsonPrimitive?.content ?: ""
                    val strat = params?.get("strategy")?.jsonPrimitive?.contentOrNull ?: "id"
                    val sub   = params?.get("value")?.jsonPrimitive?.content ?: ""
                    val tms   = params?.get("timeout_ms")?.jsonPrimitive?.intOrNull ?: 5_000
                    val txt   = adbActions.readElementText(sel, strat, tms) ?: ""
                    txt.contains(sub, ignoreCase = true)
                }
                "variable_equals" -> {
                    val key      = params?.get("key")?.jsonPrimitive?.content ?: ""
                    val expected = params?.get("value")?.jsonPrimitive?.content ?: ""
                    ctx[key]?.toString() == expected
                }
                "variable_contains" -> {
                    val key = params?.get("key")?.jsonPrimitive?.content ?: ""
                    val sub = params?.get("value")?.jsonPrimitive?.content ?: ""
                    ctx[key]?.toString()?.contains(sub, ignoreCase = true) ?: false
                }
                "http_status" -> {
                    val nodeRef = params?.get("node_id")?.jsonPrimitive?.content ?: ""
                    @Suppress("UNCHECKED_CAST")
                    val resp = ctx[nodeRef] as? Map<String, Any?> ?: emptyMap<String, Any?>()
                    val expected = params?.get("value")?.jsonPrimitive?.intOrNull ?: 200
                    resp["status_code"] as? Int == expected
                }
                else -> throw IllegalArgumentException("assert: unknown check '$check'")
            }
            if (!passed) throw AssertionError(message)
            true
        }

        // ── Loop / repeat ─────────────────────────────────────────────────────

        "loop" -> {
            val count         = action["count"]?.jsonPrimitive?.intOrNull
            val whileXpath    = action["while_xpath"]?.jsonPrimitive?.contentOrNull
            val whileStrategy = action["while_strategy"]?.jsonPrimitive?.contentOrNull ?: "xpath"
            val maxIterations = action["max_iterations"]?.jsonPrimitive?.intOrNull ?: 100
            val pollMs        = action["poll_ms"]?.jsonPrimitive?.longOrNull ?: 500L
            val bodyArray     = action["body"]?.jsonArray
                ?: throw IllegalArgumentException("loop node requires 'body' array")

            var iterations = 0
            val iterLogs   = mutableListOf<Map<String, Any?>>()

            suspend fun shouldContinue(): Boolean = when {
                count != null      -> iterations < count
                whileXpath != null -> adbActions.findElement(whileXpath, whileStrategy, 800) != null
                else               -> false
            }

            while (shouldContinue() && iterations < maxIterations && !cancelRequested) {
                for (bodyEl in bodyArray) {
                    // PERF: Лимит на кол-во логов в loop — защита от OOM при serialize.
                    // 1000 iter × 10 nodes = 10 000 entries → мегабайтный JSON → crash.
                    if (iterLogs.size >= MAX_LOOP_LOGS) {
                        Timber.w("[DAG][loop] Log limit reached ($MAX_LOOP_LOGS) — дальнейшие логи пропускаются")
                        break
                    }
                    val bodyNode = bodyEl.jsonObject
                    val bNodeId  = bodyNode["id"]?.jsonPrimitive?.contentOrNull ?: "loop_body_$iterations"
                    val bAction  = bodyNode["action"]?.jsonObject
                        ?: throw IllegalArgumentException("loop body node '$bNodeId' missing 'action'")
                    val bType = bAction["type"]!!.jsonPrimitive.content
                    val bTs   = System.currentTimeMillis()
                    try {
                        val bResult = executeNode(bType, bAction, ctx, depth + 1)
                        ctx[bNodeId] = bResult
                        iterLogs.add(mapOf("id" to bNodeId, "iter" to iterations, "ok" to true, "ms" to System.currentTimeMillis() - bTs))
                    } catch (e: Exception) {
                        iterLogs.add(mapOf("id" to bNodeId, "iter" to iterations, "ok" to false, "error" to e.message, "ms" to System.currentTimeMillis() - bTs))
                        Timber.w(e, "[DAG][loop] Body '$bNodeId' failed at iter $iterations")
                        if (bodyNode["abort_on_failure"]?.jsonPrimitive?.content?.toBoolean() == true) {
                            throw RuntimeException("loop aborted at iter $iterations node '$bNodeId': ${e.message}")
                        }
                    }
                }
                iterations++
                if (whileXpath != null) delay(pollMs)
            }
            mapOf("iterations" to iterations, "logs" to iterLogs, "logs_truncated" to (iterLogs.size >= MAX_LOOP_LOGS))
        }

        "start" -> null
        "end"   -> null

        else -> throw UnsupportedOperationException("Node type '$type' not implemented")
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun trySendProgress(commandId: String, currentNode: String, done: Int, total: Int) {
        if (!wsClient.isConnected) return
        wsClient.sendJson(buildJsonObject {
            put("type", "task_progress")
            put("task_id", commandId)
            put("current_node", currentNode)
            put("nodes_done", done)
            put("total_nodes", total)
        })
    }

    private fun makeLog(
        nodeId: String,
        actionType: String,
        durationMs: Long,
        success: Boolean,
        error: String?,
        output: Any?,
    ): JsonObject = buildJsonObject {
        put("node_id", nodeId)
        put("action_type", actionType)
        put("duration_ms", durationMs)
        put("success", success)
        error?.let { put("error", it.take(512)) }
        // PERF: Truncate output — без лимита http_request body (256KB) × 50 нод
        // = 12.8MB в node_logs JSON → OOM при JSON.encodeToString().
        output?.let {
            val str = it.toString()
            put("output", if (str.length <= MAX_LOG_OUTPUT_CHARS) str
                          else str.take(MAX_LOG_OUTPUT_CHARS) + "…[truncated ${str.length - MAX_LOG_OUTPUT_CHARS} chars]")
        }
    }

    private fun savePendingResult(commandId: String, result: JsonObject) {
        val pending = prefs.getStringSet("pending_dag_results", mutableSetOf())
            ?.toMutableSet() ?: mutableSetOf()

        // FIX AUDIT-3.6: Лимит pending results — защита от раздувания
        // EncryptedSharedPreferences при длительном offline
        if (pending.size >= MAX_PENDING_RESULTS) {
            Timber.w("[DAG] Pending results limit reached ($MAX_PENDING_RESULTS) — dropping oldest")
            // Удаляем самый старый результат (первый в Set)
            pending.iterator().let { it.next(); it.remove() }
        }

        pending.add(json.encodeToString(buildJsonObject {
            put("command_id", commandId)
            put("result", result)
            put("saved_at", System.currentTimeMillis())
        }).take(MAX_PENDING_RESULT_CHARS))
        prefs.edit().putStringSet("pending_dag_results", pending).apply()
        Timber.i("[DAG] Result saved locally, command=$commandId (pending: ${pending.size})")
    }

    // Кеширование скриптов вынесено в ScriptCacheManager (content-addressable, LRU)

    // ── HTTP helper ───────────────────────────────────────────────────────────

    /**
     * FIX H4: HTTP-запросы в DAG через OkHttpClient.
     * Ранее использовался java.net.HttpURLConnection — обход cert pinning,
     * отсутствие auth interceptor, нет connection pooling. Теперь все
     * HTTP-вызовы идут через shared OkHttpClient с теми же защитами,
     * что и остальной агент.
     */
    private suspend fun performHttpRequest(
        url: String,
        method: String,
        body: String?,
        headers: JsonObject?,
        @Suppress("UNUSED_PARAMETER") timeoutMs: Int,
    ): Map<String, Any?> = withContext(Dispatchers.IO) {
        val requestBuilder = okhttp3.Request.Builder().url(url)
        requestBuilder.addHeader("User-Agent", "SphereAgent/1.0")
        headers?.forEach { (k, v) ->
            requestBuilder.addHeader(k, v.jsonPrimitive.contentOrNull ?: "")
        }
        val requestBody = if (body != null && method in listOf("POST", "PUT", "PATCH")) {
            body.toByteArray().toRequestBody("application/json; charset=utf-8".toMediaType())
        } else null
        requestBuilder.method(method, requestBody)

        // FIX H4: Используем shared OkHttpClient (инжектирован через DI) —
        // cert pinning, auth interceptor, connection pool включены
        httpClient.newCall(requestBuilder.build()).execute().use { response ->
            val responseBody = try {
                // FIX H5: Лимит на размер response body
                response.body?.charStream()?.use { reader ->
                    val buf = CharArray(MAX_HTTP_RESPONSE_CHARS)
                    val read = reader.read(buf)
                    if (read > 0) String(buf, 0, read) else ""
                } ?: ""
            } catch (e: Exception) {
                ""
            }
            mapOf("status_code" to response.code, "body" to responseBody)
        }
    }
}
