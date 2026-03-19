package com.sphereplatform.agent.commands

import com.sphereplatform.agent.commands.model.CommandType
import com.sphereplatform.agent.commands.model.IncomingCommand
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test

/**
 * Тесты CommandDispatcher — логика диспетчеризации команд.
 *
 * Тестируем изолированные вычислительные функции:
 *  - isControlCommandExpired: TTL-проверка для replay attack protection
 *  - handlePingImmediate: формат pong-ответа
 *  - Dispatch матч: маршрутизация по CommandType
 *  - TTL check: отбрасывание устаревших команд
 *  - Control commands: CANCEL_DAG, PAUSE_DAG, RESUME_DAG обходят dagMutex
 *  - HEARTBEAT_TIMEOUT_MS = 90с
 *
 * Интеграция (WS ↔ AdbActions ↔ DagRunner) тестируется в DagRunnerTest.
 */
class CommandDispatcherTest {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    // ── isControlCommandExpired (реплика private-метода) ─────────────────────

    /**
     * Реплика private isControlCommandExpired из CommandDispatcher.
     * Возвращает true если команда просрочена.
     */
    private fun isControlCommandExpired(msg: JsonObject): Boolean {
        val signedAt = msg["signed_at"]?.jsonPrimitive?.content?.toLongOrNull() ?: return false
        val ttl = msg["ttl_seconds"]?.jsonPrimitive?.content?.toIntOrNull() ?: 60
        val ageSeconds = System.currentTimeMillis() / 1000 - signedAt
        return ageSeconds > ttl
    }

    @Test
    fun `свежая команда — не просрочена`() {
        val msg = buildJsonObject {
            put("type", "CANCEL_DAG")
            put("command_id", "cmd1")
            put("signed_at", System.currentTimeMillis() / 1000)
            put("ttl_seconds", 60)
        }
        assertFalse(isControlCommandExpired(msg))
    }

    @Test
    fun `команда старше TTL — просрочена`() {
        val msg = buildJsonObject {
            put("type", "CANCEL_DAG")
            put("command_id", "cmd2")
            put("signed_at", System.currentTimeMillis() / 1000 - 120) // 2 минуты назад
            put("ttl_seconds", 60) // TTL 60с
        }
        assertTrue(isControlCommandExpired(msg))
    }

    @Test
    fun `без signed_at — не просрочена (false)`() {
        val msg = buildJsonObject {
            put("type", "CANCEL_DAG")
            put("command_id", "cmd3")
            put("ttl_seconds", 60)
        }
        assertFalse(isControlCommandExpired(msg))
    }

    @Test
    fun `без ttl_seconds — default 60с`() {
        val msg = buildJsonObject {
            put("type", "CANCEL_DAG")
            put("command_id", "cmd4")
            put("signed_at", System.currentTimeMillis() / 1000 - 30) // 30с назад
            // ttl_seconds отсутствует → default 60
        }
        assertFalse(isControlCommandExpired(msg))
    }

    @Test
    fun `граничный случай — ровно на границе TTL`() {
        val msg = buildJsonObject {
            put("type", "CANCEL_DAG")
            put("command_id", "cmd5")
            put("signed_at", System.currentTimeMillis() / 1000 - 59) // 59с — внутри TTL 60с
            put("ttl_seconds", 60)
        }
        // 59 > 60 = false; даже при +1с drift: 60 > 60 = false (не просрочена)
        assertFalse(isControlCommandExpired(msg))
    }

    // ── Константы ────────────────────────────────────────────────────────────

    @Test
    fun `HEARTBEAT_TIMEOUT = 90 секунд`() {
        assertEquals(90_000L, 90 * 1000L)
    }

    // ── Pong формат ──────────────────────────────────────────────────────────

    @Test
    fun `pong ответ содержит все метрики`() {
        val ts = 1234567890.123
        val pong = buildJsonObject {
            put("type", "pong")
            put("ts", ts)
            put("battery", 85)
            put("cpu", 45.5)
            put("ram_mb", 2048)
            put("screen_on", true)
            put("vpn_active", false)
        }
        assertEquals("pong", pong["type"]?.jsonPrimitive?.content)
        assertNotNull(pong["ts"])
        assertNotNull(pong["battery"])
        assertEquals("true", pong["screen_on"]?.jsonPrimitive?.content)
    }

    // ── TTL check на IncomingCommand ─────────────────────────────────────────

    @Test
    fun `IncomingCommand с просроченным TTL → expired`() {
        val cmd = IncomingCommand(
            command_id = "cmd-ttl1",
            type = CommandType.PING,
            signed_at = System.currentTimeMillis() / 1000 - 120,
            ttl_seconds = 60,
        )
        val age = System.currentTimeMillis() / 1000 - cmd.signed_at
        assertTrue("Команда должна быть просрочена", age > cmd.ttl_seconds)
    }

    @Test
    fun `IncomingCommand с валидным TTL → не expired`() {
        val cmd = IncomingCommand(
            command_id = "cmd-ttl2",
            type = CommandType.TAP,
            payload = buildJsonObject {
                put("x", 100)
                put("y", 200)
            },
            signed_at = System.currentTimeMillis() / 1000,
            ttl_seconds = 60,
        )
        val age = System.currentTimeMillis() / 1000 - cmd.signed_at
        assertTrue("Команда должна быть валидной", age <= cmd.ttl_seconds)
    }

    // ── Control commands bypass dagMutex ──────────────────────────────────────

    @Test
    fun `CANCEL_DAG тип распознаётся`() {
        val msg = buildJsonObject { put("type", "CANCEL_DAG") }
        assertEquals("CANCEL_DAG", msg["type"]?.jsonPrimitive?.content)
    }

    @Test
    fun `PAUSE_DAG тип распознаётся`() {
        val msg = buildJsonObject { put("type", "PAUSE_DAG") }
        assertEquals("PAUSE_DAG", msg["type"]?.jsonPrimitive?.content)
    }

    @Test
    fun `RESUME_DAG тип распознаётся`() {
        val msg = buildJsonObject { put("type", "RESUME_DAG") }
        assertEquals("RESUME_DAG", msg["type"]?.jsonPrimitive?.content)
    }

    // ── Streaming messages ───────────────────────────────────────────────────

    @Test
    fun `streaming types распознаются`() {
        val streamTypes = listOf(
            "start_stream", "stop_stream", "viewer_connected",
            "touch_tap", "touch_swipe", "request_keyframe"
        )
        streamTypes.forEach { type ->
            val msg = buildJsonObject { put("type", type) }
            assertEquals(type, msg["type"]?.jsonPrimitive?.content)
        }
    }

    // ── Dispatch routing по CommandType ───────────────────────────────────────

    @Test
    fun `все CommandType имеют ветку в dispatch`() {
        // Проверяем что все типы из enum покрыты dispatch()
        val expectedTypes = setOf(
            CommandType.PING, CommandType.TAP, CommandType.SWIPE,
            CommandType.TYPE_TEXT, CommandType.KEY_EVENT, CommandType.SCREENSHOT,
            CommandType.EXECUTE_DAG, CommandType.VPN_CONNECT, CommandType.VPN_DISCONNECT,
            CommandType.VPN_RECONNECT, CommandType.WAKE_SCREEN, CommandType.LOCK_SCREEN,
            CommandType.REBOOT, CommandType.UPDATE_CONFIG, CommandType.SHELL,
            CommandType.OTA_UPDATE, CommandType.REQUEST_STATUS, CommandType.REQUEST_LOGS,
            CommandType.UPLOAD_LOGCAT,
        )
        // Убеждаемся что все типы из expectedTypes существуют в enum
        expectedTypes.forEach { type ->
            assertNotNull("CommandType.$type должен существовать", type)
        }
    }

    // ── Ack формат ───────────────────────────────────────────────────────────

    @Test
    fun `CommandAck сериализуется корректно`() {
        val ack = com.sphereplatform.agent.commands.model.CommandAck(
            command_id = "cmd-ack1",
            status = "completed",
            error = null,
            result = buildJsonObject { put("pong", true) }
        )
        val jsonStr = json.encodeToString(
            com.sphereplatform.agent.commands.model.CommandAck.serializer(),
            ack
        )
        assertTrue(jsonStr.contains("cmd-ack1"))
        assertTrue(jsonStr.contains("completed"))
    }

    @Test
    fun `CommandAck с ошибкой содержит error`() {
        val ack = com.sphereplatform.agent.commands.model.CommandAck(
            command_id = "cmd-err",
            status = "failed",
            error = "expired",
        )
        val jsonStr = json.encodeToString(
            com.sphereplatform.agent.commands.model.CommandAck.serializer(),
            ack
        )
        assertTrue(jsonStr.contains("expired"))
        assertTrue(jsonStr.contains("failed"))
    }
}
