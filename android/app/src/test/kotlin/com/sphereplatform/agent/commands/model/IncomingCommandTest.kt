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
    fun `число CommandType — 21 тип`() {
        assertEquals(21, CommandType.entries.size)
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
