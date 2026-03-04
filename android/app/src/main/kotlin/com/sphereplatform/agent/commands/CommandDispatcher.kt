package com.sphereplatform.agent.commands

import android.content.Context
import android.content.Intent
import com.sphereplatform.agent.commands.model.CommandAck
import com.sphereplatform.agent.commands.model.CommandType
import com.sphereplatform.agent.commands.model.IncomingCommand
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.logging.LogcatCollector
import com.sphereplatform.agent.ota.OtaUpdatePayload
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.providers.DeviceStatusProvider
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.streaming.ScreenCaptureRequestActivity
import com.sphereplatform.agent.streaming.ScreenCaptureService
import com.sphereplatform.agent.streaming.StreamingManager
import com.sphereplatform.agent.streaming.StreamingManagerImpl
import com.sphereplatform.agent.vpn.KillSwitchManager
import com.sphereplatform.agent.vpn.SphereVpnManager
import com.sphereplatform.agent.ws.SphereWebSocketClient
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
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
    private val scriptCache: ScriptCacheManager,
    private val vpnManager: SphereVpnManager,
    private val killSwitchManager: KillSwitchManager,
    private val authStore: AuthTokenStore,
    private val otaUpdateService: OtaUpdateService,
    private val deviceStatusProvider: DeviceStatusProvider,
    private val fileLoggingTree: FileLoggingTree,
    private val logcatCollector: LogcatCollector,
    private val scope: CoroutineScope,
    private val streamingManager: StreamingManager,
    @ApplicationContext private val appContext: Context,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    // Serialises concurrent EXECUTE_DAG commands: only 1 DAG runs per device at a time.
    // If a second DAG arrives while one is running, it queues and waits.
    private val dagMutex = Mutex()

    // FIX AUDIT-2.5: Application-level heartbeat watchdog
    // Если сервер не шлёт ping >90с — WS, скорее всего, мёртв
    @Volatile private var lastPingAt = System.currentTimeMillis()
    private val HEARTBEAT_TIMEOUT_MS = 90_000L // 90с (ping приходит каждые ~15-30с)

    /** FIX D1: Job heartbeat watchdog — отменяется в stop(). */
    private var heartbeatJob: kotlinx.coroutines.Job? = null

    fun start() {
        wsClient.onJsonMessage = { msg ->
            val type = msg["type"]?.jsonPrimitive?.contentOrNull
            if (type == "ping") {
                handlePingImmediate(msg)
            } else {
                scope.launch { handleMessage(msg) }
            }
        }

        // При reconnect — отправляем накопленные результаты DAG и сбрасываем heartbeat
        wsClient.onConnected = {
            lastPingAt = System.currentTimeMillis()
            scope.launch { dagRunner.flushPendingResults() }
        }

        // FIX AUDIT-2.5: Heartbeat watchdog — если сервер не шлёт ping > 90с,
        // принудительный reconnect. Компенсирует кейс когда readTimeout
        // не срабатывает (данные шли, но ping прекратился).
        // FIX D1: Сохраняем Job для отмены в stop(). Без этого при рестарте
        // сервиса создавалось N дублирующих watchdog-циклов.
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch(Dispatchers.Default) {
            while (true) {
                delay(30_000L) // Проверяем каждые 30с
                if (wsClient.isConnected) {
                    val elapsed = System.currentTimeMillis() - lastPingAt
                    if (elapsed > HEARTBEAT_TIMEOUT_MS) {
                        Timber.w("Heartbeat watchdog: no ping for ${elapsed/1000}s — forcing reconnect")
                        wsClient.forceReconnectNow()
                        lastPingAt = System.currentTimeMillis() // Сброс чтобы не спамить
                    }
                }
            }
        }
    }

    /**
     * FIX D1: Останавливает heartbeat watchdog и сбрасывает callbacks.
     * Вызывается из SphereAgentService.onDestroy() перед отменой serviceScope.
     */
    fun stop() {
        heartbeatJob?.cancel()
        heartbeatJob = null
        wsClient.onJsonMessage = null
        wsClient.onConnected = null
    }

    /**
     * FIX D7: TTL-проверка для управляющих команд (CANCEL/PAUSE/RESUME_DAG).
     * Эти команды обходят IncomingCommand десериализацию, поэтому TTL
     * проверяется вручную. Защита от replay attack: повторная отправка
     * устаревшей CANCEL_DAG не должна останавливать новый DAG.
     *
     * @return true если команда просрочена и был отправлен failed ack.
     */
    private fun isControlCommandExpired(msg: JsonObject, cmdId: String): Boolean {
        val signedAt = msg["signed_at"]?.jsonPrimitive?.longOrNull ?: return false
        val ttl = msg["ttl_seconds"]?.jsonPrimitive?.intOrNull ?: 60
        val ageSeconds = System.currentTimeMillis() / 1000 - signedAt
        if (ageSeconds > ttl) {
            Timber.w("[$cmdId] Control command expired (age=${ageSeconds}s > ttl=${ttl}s)")
            ack(cmdId, "failed", error = "expired")
            return true
        }
        return false
    }

    /**
     * Обрабатывает ping синхронно, без корутинного пула.
     * Критично для длинных DAG: executor потоки заняты, но pong ДОЛЖЕН уйти.
     *
     * FIX M5: Метрики берутся из кэша DeviceStatusProvider (5с TTL),
     * поэтому блокировка WS reader thread минимальна (<1ms если кэш горячий).
     * При холодном кэше getCpuUsage() парсит /proc/stat (procfs, ~5ms),
     * что приемлемо для WS reader thread.
     */
    private fun handlePingImmediate(msg: JsonObject) {
        // FIX AUDIT-2.5: Обновляем heartbeat timestamp
        lastPingAt = System.currentTimeMillis()
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
        // System streaming messages — NOT IncomingCommand format, handle first
        when (msg["type"]?.jsonPrimitive?.contentOrNull) {
            "start_stream" -> {
                Timber.i("Received start_stream — launching screen capture permission dialog")
                val intent = Intent(appContext, ScreenCaptureRequestActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                appContext.startActivity(intent)
                return
            }
            "stop_stream" -> {
                Timber.i("Received stop_stream — stopping screen capture")
                val stopIntent = Intent(appContext, ScreenCaptureService::class.java).apply {
                    action = ScreenCaptureService.ACTION_STOP
                }
                appContext.startService(stopIntent)
                return
            }
            "viewer_connected" -> {
                Timber.i("Received viewer_connected — requesting keyframe")
                (streamingManager as? StreamingManagerImpl)?.onViewerConnected()
                return
            }
            "touch_tap" -> {
                val x = msg["x"]?.jsonPrimitive?.intOrNull ?: return
                val y = msg["y"]?.jsonPrimitive?.intOrNull ?: return
                scope.launch { adbActions.tap(x, y) }
                return
            }
            "touch_swipe" -> {
                val x1 = msg["x1"]?.jsonPrimitive?.intOrNull ?: return
                val y1 = msg["y1"]?.jsonPrimitive?.intOrNull ?: return
                val x2 = msg["x2"]?.jsonPrimitive?.intOrNull ?: return
                val y2 = msg["y2"]?.jsonPrimitive?.intOrNull ?: return
                val duration = msg["duration_ms"]?.jsonPrimitive?.intOrNull ?: 300
                scope.launch { adbActions.swipe(x1, y1, x2, y2, duration) }
                return
            }
            "request_keyframe" -> {
                (streamingManager as? StreamingManagerImpl)?.onViewerConnected()
                return
            }
            // ── CANCEL_DAG: bypass dagMutex ──
            "CANCEL_DAG" -> {
                val cmdId = msg["command_id"]?.jsonPrimitive?.contentOrNull ?: ""
                // FIX D7: TTL-проверка для управляющих команд (защита от replay attack)
                if (isControlCommandExpired(msg, cmdId)) return
                Timber.i("[CANCEL_DAG] Received cancel for command=$cmdId")
                dagRunner.requestCancel()
                ack(cmdId, "completed")
                return
            }
            // ── PAUSE_DAG: bypass dagMutex, пауза работающего DAG между нодами ──
            "PAUSE_DAG" -> {
                val cmdId = msg["command_id"]?.jsonPrimitive?.contentOrNull ?: ""
                if (isControlCommandExpired(msg, cmdId)) return
                Timber.i("[PAUSE_DAG] Received pause for command=$cmdId")
                dagRunner.requestPause()
                ack(cmdId, "completed")
                return
            }
            // ── RESUME_DAG: bypass dagMutex, снятие паузы ──
            "RESUME_DAG" -> {
                val cmdId = msg["command_id"]?.jsonPrimitive?.contentOrNull ?: ""
                if (isControlCommandExpired(msg, cmdId)) return
                Timber.i("[RESUME_DAG] Received resume for command=$cmdId")
                dagRunner.requestResume()
                ack(cmdId, "completed")
                return
            }
        }

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
            val dagName = cmd.payload["dag_name"]?.jsonPrimitive?.contentOrNull
            val dagHash = cmd.payload["dag_hash"]?.jsonPrimitive?.contentOrNull

            // Контент-адресабльный кеш: если имя + hash присланы — ищем в кеше
            val dagJson: JsonObject = if (dagName != null && dagHash != null) {
                when (val cacheResult = scriptCache.get(dagName, dagHash)) {
                    is ScriptCacheManager.CacheResult.Hit -> {
                        // Кеш-хит: DAG актуален, запускаем без пердачи по WS
                        Timber.i("[EXECUTE_DAG] Кеш-хит 'скрипт $dagName' — запуск без загрузки")
                        cacheResult.dag
                    }
                    is ScriptCacheManager.CacheResult.HashMismatch -> {
                        // Скрипт изменился — обновляем кеш из payload
                        val fresh = cmd.payload["dag"]?.jsonObject
                            ?: error("Скрипт 'скрипт $dagName' изменился (hash не совпадает), но DAG не передан в payload")
                        scriptCache.put(dagName, dagHash, fresh)
                        Timber.i("[EXECUTE_DAG] Обновлён кеш 'скрипт $dagName' (hash изменился)")
                        fresh
                    }
                    ScriptCacheManager.CacheResult.Miss -> {
                        // Первый запуск: кешируем из payload
                        val fresh = cmd.payload["dag"]?.jsonObject
                            ?: error("Кеш-мисс для 'скрипт $dagName': DAG не передан в payload")
                        scriptCache.put(dagName, dagHash, fresh)
                        Timber.i("[EXECUTE_DAG] Кеш-мисс 'скрипт $dagName' — скеширован")
                        fresh
                    }
                }
            } else {
                // Классический путь (без кеширования): dag обязателен
                cmd.payload["dag"]?.jsonObject
                    ?: error("Поле 'dag' обязательно в payload EXECUTE_DAG")
            }

            // Mutex гарантирует не более одного активного DAG за раз
            dagMutex.withLock {
                dagRunner.execute(cmd.command_id, dagJson)
            }
        }

        CommandType.VPN_CONNECT -> {
            val config = cmd.payload["config"]!!.jsonPrimitive.content
            vpnManager.connect(config)
            // Enable kill switch with management server carve-out
            val vpnEndpoint = cmd.payload["endpoint"]?.jsonPrimitive?.content
            if (vpnEndpoint != null) {
                val mgmtHost = authStore.getServerUrl()
                    .removePrefix("https://").removePrefix("http://")
                    .substringBefore("/").substringBefore(":")
                killSwitchManager.enable(vpnEndpoint, listOf(mgmtHost))
            }
            null
        }

        CommandType.VPN_DISCONNECT -> {
            killSwitchManager.disable()
            vpnManager.disconnect()
            null
        }

        CommandType.VPN_RECONNECT -> {
            vpnManager.reconnect()
            null
        }

        CommandType.WAKE_SCREEN -> {
            adbActions.wakeScreen()
            null
        }

        CommandType.LOCK_SCREEN -> {
            adbActions.lockScreen()
            null
        }

        CommandType.REBOOT -> {
            adbActions.reboot()
            null
        }

        CommandType.UPDATE_CONFIG -> {
            val serverUrl = cmd.payload["server_url"]?.jsonPrimitive?.contentOrNull
            val apiKey = cmd.payload["api_key"]?.jsonPrimitive?.contentOrNull
            val deviceId = cmd.payload["device_id"]?.jsonPrimitive?.contentOrNull
            if (serverUrl != null) authStore.saveServerUrl(serverUrl)
            if (apiKey != null) authStore.saveApiKey(apiKey)
            if (deviceId != null) authStore.saveDeviceId(deviceId)
            buildJsonObject { put("updated", true) }
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

        CommandType.REQUEST_LOGS -> {
            val maxBytes = cmd.payload["max_bytes"]?.jsonPrimitive?.intOrNull ?: (64 * 1024)
            val content = fileLoggingTree.readRecentLogs(maxBytes)
            buildJsonObject { put("logs", content) }
        }

        CommandType.UPLOAD_LOGCAT -> {
            val lines = cmd.payload["lines"]?.jsonPrimitive?.intOrNull ?: 500
            val mode = cmd.payload["mode"]?.jsonPrimitive?.content ?: "sphere"
            val content = when (mode) {
                "full"   -> logcatCollector.collectSystemFull(lines)
                "sphere" -> logcatCollector.collectSphereOnly(lines)
                else     -> logcatCollector.collect(lines)
            }
            buildJsonObject { put("logcat", content) }
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

private val kotlinx.serialization.json.JsonPrimitive.longOrNull: Long?
    get() = runCatching { this.content.toLong() }.getOrNull()
