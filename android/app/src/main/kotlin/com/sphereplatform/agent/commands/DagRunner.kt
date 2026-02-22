package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import com.sphereplatform.agent.lua.LuaEngine
import com.sphereplatform.agent.ws.SphereWebSocketClient
import kotlinx.coroutines.delay
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * DagRunner — исполняет DAG-скрипты команд.
 *
 * Каждый узел DAG выполняется последовательно, результат передаётся
 * в контекст следующего узла.
 *
 * # FIX ARCH-1: Промежуточный прогресс
 * task_progress отправляется после каждого узла — дашборд видит прогресс DAG
 * в реальном времени, не только финальный результат.
 *
 * # FIX ARCH-2: Pending results при потере WS
 * Если WS упал в процессе DAG — результат сохраняется в EncryptedSharedPreferences.
 * При следующем reconnect [flushPendingResults] отправляет накопленное.
 */
@Singleton
class DagRunner @Inject constructor(
    private val luaEngine: LuaEngine,
    private val adbActions: AdbActionExecutor,
    private val wsClient: SphereWebSocketClient,
    private val prefs: EncryptedSharedPreferences,
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun execute(commandId: String, dagJson: JsonObject): JsonObject {
        val startNodeId = dagJson["entry_node"]!!.jsonPrimitive.content
        val nodes = dagJson["nodes"]!!.jsonObject

        val results = mutableMapOf<String, Any?>()
        var currentNodeId: String? = startNodeId

        while (currentNodeId != null) {
            val node = nodes[currentNodeId]?.jsonObject
                ?: throw IllegalArgumentException("Node $currentNodeId not found in DAG")

            val nodeType = node["type"]!!.jsonPrimitive.content
            val result = executeNode(nodeType, node, results)
            results[currentNodeId] = result

            // FIX ARCH-1: Прогресс после каждого узла
            if (wsClient.isConnected) {
                wsClient.sendJson(buildJsonObject {
                    put("type", "task_progress")
                    put("task_id", commandId)
                    put("current_node", currentNodeId)
                    put("nodes_done", results.size)
                    put("total_nodes", nodes.size)
                })
            }

            currentNodeId = resolveNextNode(nodeType, node, result)
        }

        val finalResult = buildJsonObject {
            put("nodes_executed", results.size)
            put("success", true)
        }

        // FIX ARCH-2: Сохраняем результат если WS недоступен
        if (!wsClient.isConnected) {
            savePendingResult(commandId, finalResult)
        }

        return finalResult
    }

    /**
     * Отправить накопленные результаты DAG при reconnect.
     * Вызывается из [SphereWebSocketClient.onConnected] callback.
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

    private suspend fun executeNode(
        type: String,
        node: JsonObject,
        ctx: Map<String, Any?>,
    ): Any? = when (type) {
        "Tap" -> {
            val x = node["x"]!!.jsonPrimitive.int
            val y = node["y"]!!.jsonPrimitive.int
            adbActions.tap(x, y)
            null
        }

        "Swipe" -> {
            val x1 = node["x1"]!!.jsonPrimitive.int
            val y1 = node["y1"]!!.jsonPrimitive.int
            val x2 = node["x2"]!!.jsonPrimitive.int
            val y2 = node["y2"]!!.jsonPrimitive.int
            val dur = node["duration_ms"]?.jsonPrimitive?.int ?: 300
            adbActions.swipe(x1, y1, x2, y2, dur)
            null
        }

        "KeyEvent" -> {
            val code = node["key_code"]!!.jsonPrimitive.int
            adbActions.keyEvent(code)
            null
        }

        "Sleep" -> {
            val ms = node["duration_ms"]!!.jsonPrimitive.long
            delay(ms)
            null
        }

        "Lua" -> {
            val code = node["code"]!!.jsonPrimitive.content
            luaEngine.executeWithTimeout(code, ctx)
        }

        "End" -> null

        else -> throw UnsupportedOperationException("Node type '$type' not implemented")
    }

    private fun resolveNextNode(type: String, node: JsonObject, result: Any?): String? {
        if (type == "Condition") {
            val branch = if (result as? Boolean == true) "true_branch" else "false_branch"
            return node["links"]?.jsonObject?.get(branch)?.jsonPrimitive?.content
        }
        return node["links"]?.jsonObject?.get("next")?.jsonPrimitive?.content
    }

    private fun savePendingResult(commandId: String, result: JsonObject) {
        val pending = prefs.getStringSet("pending_dag_results", mutableSetOf())
            ?.toMutableSet() ?: mutableSetOf()
        pending.add(json.encodeToString(buildJsonObject {
            put("command_id", commandId)
            put("result", result)
            put("saved_at", System.currentTimeMillis())
        }))
        prefs.edit().putStringSet("pending_dag_results", pending).apply()
        Timber.i("[DAG] Result saved locally, command=$commandId")
    }
}
