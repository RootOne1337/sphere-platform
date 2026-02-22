package com.sphereplatform.agent.commands

import com.sphereplatform.agent.commands.model.CommandAck
import com.sphereplatform.agent.commands.model.CommandType
import com.sphereplatform.agent.commands.model.IncomingCommand
import com.sphereplatform.agent.ota.OtaUpdatePayload
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.providers.DeviceStatusProvider
import com.sphereplatform.agent.vpn.SphereVpnManager
import com.sphereplatform.agent.ws.SphereWebSocketClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CommandDispatcher @Inject constructor(
    private val wsClient: SphereWebSocketClient,
    private val adbActions: AdbActionExecutor,
    private val dagRunner: DagRunner,
    private val vpnManager: SphereVpnManager,
    private val otaUpdateService: OtaUpdateService,
    private val deviceStatusProvider: DeviceStatusProvider,
    private val scope: CoroutineScope,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    fun start() {
        wsClient.onJsonMessage = { msg ->
            // FIX ARCH-4: ping обрабатываем НЕМЕДЛЕННО в потоке callback'а,
            // не через scope.launch. DagRunner может блокировать Dispatchers.IO,
            // а pong ДОЛЖЕН уйти в рамках heartbeat timeout (TZ-03 SPLIT-4: 45s).
            val type = msg["type"]?.jsonPrimitive?.contentOrNull
            if (type == "ping") {
                handlePingImmediate(msg)
            } else {
                scope.launch { handleMessage(msg) }
            }
        }

        // При reconnect — отправляем накопленные результаты DAG
        wsClient.onConnected = {
            scope.launch { dagRunner.flushPendingResults() }
        }
    }

    /**
     * Обрабатывает ping синхронно, без корутинного пула.
     * Критично для длинных DAG: executor потоки заняты, но pong ДОЛЖЕН уйти.
     */
    private fun handlePingImmediate(msg: JsonObject) {
        val ts = msg["ts"]?.jsonPrimitive?.doubleOrNull ?: 0.0
        wsClient.sendJson(buildJsonObject {
            put("type", "pong")
            put("ts", ts)
            put("battery", deviceStatusProvider.getBatteryLevel())
            put("cpu", deviceStatusProvider.getCpuUsage())
            put("ram_mb", deviceStatusProvider.getRamUsageMb())
            put("screen_on", deviceStatusProvider.isScreenOn())
            put("vpn_active", deviceStatusProvider.isVpnActive())
        })
    }

    private suspend fun handleMessage(msg: JsonObject) {
        val cmd = try {
            json.decodeFromJsonElement<IncomingCommand>(msg)
        } catch (e: Exception) {
            Timber.w("Cannot parse command: ${e.message}")
            return
        }

        // TTL check — отбрасываем устаревшие команды
        val ageSeconds = System.currentTimeMillis() / 1000 - cmd.signed_at
        if (ageSeconds > cmd.ttl_seconds) {
            Timber.w("[${cmd.command_id}] Expired (age=${ageSeconds}s > ttl=${cmd.ttl_seconds}s)")
            ack(cmd.command_id, "failed", error = "expired")
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
            ack(cmd.command_id, "failed", error = err)
        }
    }

    private suspend fun dispatch(cmd: IncomingCommand): JsonObject? = when (cmd.type) {
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
            val duration = cmd.payload["duration_ms"]?.jsonPrimitive?.intOrNull ?: 300
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

        CommandType.VPN_DISCONNECT -> {
            vpnManager.disconnect()
            null
        }

        CommandType.VPN_RECONNECT -> {
            vpnManager.reconnect()
            null
        }

        CommandType.SHELL -> {
            val command = cmd.payload["cmd"]!!.jsonPrimitive.content
            val output = adbActions.shell(command)
            buildJsonObject { put("output", output) }
        }

        CommandType.OTA_UPDATE -> {
            val payload = json.decodeFromJsonElement<OtaUpdatePayload>(cmd.payload)
            otaUpdateService.performUpdate(payload)
            buildJsonObject { put("status", "download_complete") }
        }

        CommandType.REQUEST_STATUS -> {
            buildJsonObject {
                put("battery", deviceStatusProvider.getBatteryLevel())
                put("cpu", deviceStatusProvider.getCpuUsage())
                put("ram_mb", deviceStatusProvider.getRamUsageMb())
                put("screen_on", deviceStatusProvider.isScreenOn())
                put("vpn_active", deviceStatusProvider.isVpnActive())
            }
        }

        else -> {
            Timber.w("Unhandled command type: ${cmd.type}")
            null
        }
    }

    private fun ack(
        commandId: String,
        status: String,
        error: String? = null,
        result: JsonObject? = null,
    ) {
        val ack = CommandAck(commandId, status, error, result)
        wsClient.sendJson(
            json.parseToJsonElement(json.encodeToString(ack)).jsonObject
        )
    }
}

// Вспомогательное extension для nullable jsonPrimitive
private val kotlinx.serialization.json.JsonPrimitive.doubleOrNull: Double?
    get() = runCatching { this.content.toDouble() }.getOrNull()

private val kotlinx.serialization.json.JsonPrimitive.intOrNull: Int?
    get() = runCatching { this.content.toInt() }.getOrNull()
