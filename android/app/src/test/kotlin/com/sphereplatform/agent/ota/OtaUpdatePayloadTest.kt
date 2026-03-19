package com.sphereplatform.agent.ota

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

/**
 * Тесты OtaUpdatePayload — модель данных OTA-обновления.
 *
 * Покрытие:
 *  - Полная десериализация
 *  - Дефолт force=false
 *  - Round-trip
 *  - Невалидный JSON
 */
class OtaUpdatePayloadTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun `полная десериализация`() {
        val raw = """
            {
                "download_url": "https://example.com/update.apk",
                "version": "1.2.3",
                "sha256": "abc123def456",
                "force": true
            }
        """.trimIndent()
        val payload = json.decodeFromString<OtaUpdatePayload>(raw)
        assertEquals("https://example.com/update.apk", payload.download_url)
        assertEquals("1.2.3", payload.version)
        assertEquals("abc123def456", payload.sha256)
        assertTrue(payload.force)
    }

    @Test
    fun `дефолт force = false`() {
        val raw = """{"download_url":"u","version":"v","sha256":"h"}"""
        val payload = json.decodeFromString<OtaUpdatePayload>(raw)
        assertFalse(payload.force)
    }

    @Test
    fun `round-trip сериализация`() {
        val original = OtaUpdatePayload(
            download_url = "https://server.com/agent.apk",
            version = "2.0.0",
            sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            force = true,
        )
        val str = json.encodeToString(original)
        val restored = json.decodeFromString<OtaUpdatePayload>(str)
        assertEquals(original, restored)
    }

    @Test(expected = Exception::class)
    fun `отсутствует download_url → исключение`() {
        json.decodeFromString<OtaUpdatePayload>("""{"version":"v","sha256":"h"}""")
    }

    @Test(expected = Exception::class)
    fun `отсутствует version → исключение`() {
        json.decodeFromString<OtaUpdatePayload>("""{"download_url":"u","sha256":"h"}""")
    }

    @Test(expected = Exception::class)
    fun `отсутствует sha256 → исключение`() {
        json.decodeFromString<OtaUpdatePayload>("""{"download_url":"u","version":"v"}""")
    }
}
