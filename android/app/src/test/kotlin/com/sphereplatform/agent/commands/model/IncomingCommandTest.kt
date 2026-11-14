package com.sphereplatform.agent.commands.model

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test

/**
 * Тесты IncomingCommand — десериализация WS-команд.
 *
 * Покрытие:
 *  - Полная десериализация всех полей
 *  - Дефолтные значения (payload=empty, ttl_seconds=60)
 *  - Каждый CommandType десериализуется из строки
 *  - Сериализация обратно в JSON
 *  - Невалидные входные данные
 */
class IncomingCommandTest {
    @Test fun commandAckContainsServerRoutingDiscriminator() {
        val encoded = Json.encodeToString(CommandAck("audit-command", "completed"))
        val obj = Json.parseToJsonElement(encoded) as JsonObject
        assertEquals(kotlinx.serialization.json.JsonPrimitive("command_result"), obj["type"])
    }

    private val json = Json { ignoreUnknownKeys = true }

    // ── Десериализация ───────────────────────────────────────────────────────

    @Test
    fun `полная десериализация`() {
        val raw = """
            {
                "command_id": "cmd-001",
                "type": "TAP",
                "payload": {"x": 100, "y": 200},
                "signed_at": 1740000000,
                "ttl_seconds": 30
            }
        """.trimIndent()
        val cmd = json.decodeFromString<IncomingCommand>(raw)
        assertEquals("cmd-001", cmd.command_id)
        assertEquals(CommandType.TAP, cmd.type)
        assertEquals(1740000000L, cmd.signed_at)
        assertEquals(30, cmd.ttl_seconds)
        assertTrue(cmd.payload.containsKey("x"))
    }

    @Test
    fun `дефолт payload = empty JsonObject`() {
        val raw = """{"command_id":"x","type":"PING","signed_at":0}"""
        val cmd = json.decodeFromString<IncomingCommand>(raw)
        assertEquals(JsonObject(emptyMap()), cmd.payload)
    }

    @Test
    fun `дефолт ttl_seconds = 60`() {
        val raw = """{"command_id":"x","type":"PING","signed_at":0}"""
        val cmd = json.decodeFromString<IncomingCommand>(raw)
        assertEquals(60, cmd.ttl_seconds)
    }

    // ── Все CommandType ──────────────────────────────────────────────────────

    @Test
    fun `десериализация всех CommandType`() {
        val types = CommandType.entries
        for (type in types) {
            val raw = """{"command_id":"t","type":"${type.name}","signed_at":0}"""
            val cmd = json.decodeFromString<IncomingCommand>(raw)
            assertEquals(type, cmd.type)
        }
    }

    @Test
    fun `команды прежних APK сохраняют wire имена`() {
        val legacy = setOf(
            "WAKE_SCREEN", "LOCK_SCREEN", "REBOOT", "SHELL", "TAP", "SWIPE",
            "TYPE_TEXT", "KEY_EVENT", "SCREENSHOT", "EXECUTE_DAG", "PAUSE_DAG",
            "RESUME_DAG", "VPN_CONNECT", "VPN_DISCONNECT", "VPN_RECONNECT",
            "OTA_UPDATE", "PING", "UPDATE_CONFIG", "REQUEST_STATUS", "REQUEST_LOGS",
            "UPLOAD_LOGCAT",
        )
        val names = CommandType.entries.map { it.name }.toSet()
        assertTrue("An existing server command was removed or renamed", names.containsAll(legacy))
    }

    @Test
    fun `app VPN команды совместимы с JSON протоколом сервера`() {
        val commands = mapOf(
            "VPN_APP_OPERATION" to CommandType.VPN_APP_OPERATION,
            "VPN_APP_STATUS" to CommandType.VPN_APP_STATUS,
            "VPN_APP_CONSENT" to CommandType.VPN_APP_CONSENT,
            "VPN_APP_RECIPIENT" to CommandType.VPN_APP_RECIPIENT,
        )
        for ((wireName, expected) in commands) {
            val decoded = json.decodeFromString<IncomingCommand>(
                """{"command_id":"vpn-operation","type":"$wireName","signed_at":0}""",
            )
            assertEquals(expected, decoded.type)
            val encoded = json.parseToJsonElement(json.encodeToString(decoded)) as JsonObject
            assertEquals(kotlinx.serialization.json.JsonPrimitive(wireName), encoded["type"])
        }
    }

    @Test
    fun `CommandType содержит критичные типы`() {
        val names = CommandType.entries.map { it.name }.toSet()
        assertTrue("EXECUTE_DAG", "EXECUTE_DAG" in names)
        assertTrue("PING", "PING" in names)
        assertTrue("OTA_UPDATE", "OTA_UPDATE" in names)
        assertTrue("VPN_CONNECT", "VPN_CONNECT" in names)
        assertTrue("SHELL", "SHELL" in names)
        assertTrue("PAUSE_DAG", "PAUSE_DAG" in names)
        assertTrue("RESUME_DAG", "RESUME_DAG" in names)
    }

    // ── Сериализация ─────────────────────────────────────────────────────────

    @Test
    fun `round-trip сериализация`() {
        val original = IncomingCommand(
            command_id = "abc-123",
            type = CommandType.EXECUTE_DAG,
            payload = buildJsonObject { put("dag", "test") },
            signed_at = 9999L,
            ttl_seconds = 120,
        )
        val jsonStr = json.encodeToString(original)
        val restored = json.decodeFromString<IncomingCommand>(jsonStr)
        assertEquals(original, restored)
    }

    // ── CommandAck ───────────────────────────────────────────────────────────

    @Test
    fun `CommandAck сериализация`() {
        val ack = CommandAck(
            command_id = "cmd-001",
            status = "completed",
            error = null,
            result = buildJsonObject { put("ok", true) },
        )
        val jsonStr = json.encodeToString(ack)
        assertTrue(jsonStr.contains("\"completed\""))
    }

    @Test
    fun `CommandAck с ошибкой`() {
        val ack = CommandAck("cmd-002", "failed", error = "timeout")
        val restored = json.decodeFromString<CommandAck>(json.encodeToString(ack))
        assertEquals("failed", restored.status)
        assertEquals("timeout", restored.error)
    }

    // ── Невалидный вход ──────────────────────────────────────────────────────

    @Test(expected = Exception::class)
    fun `невалидный type → исключение`() {
        json.decodeFromString<IncomingCommand>(
            """{"command_id":"x","type":"INVALID_TYPE","signed_at":0}"""
        )
    }

    @Test(expected = Exception::class)
    fun `отсутствует command_id → исключение`() {
        json.decodeFromString<IncomingCommand>(
            """{"type":"PING","signed_at":0}"""
        )
    }
}
