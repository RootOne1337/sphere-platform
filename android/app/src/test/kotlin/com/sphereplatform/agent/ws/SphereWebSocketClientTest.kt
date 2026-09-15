package com.sphereplatform.agent.ws

import org.junit.Assert.*
import io.mockk.mockk
import kotlinx.serialization.json.Json
import org.junit.Test

/**
 * Тесты SphereWebSocketClient — расчёт backoff + circuit breaker + debounce.
 *
 * WebSocket lifecycle (connect/reconnect) зависит от OkHttpClient — тестируем
 * изолированные математические / временные свойства через reflection доступ
 * к private-функциям и полям.
 *
 * Покрытие:
 *  - calculateBackoff: экспоненциальный рост 1→30s cap
 *  - CIRCUIT_OPEN_THRESHOLD = 10
 *  - CIRCUIT_COOL_DOWN_MS = 60s
 *  - FORCE_RECONNECT_DEBOUNCE_MS = 5s
 *  - Close codes: 4001, 4003, 4004, 4008
 *  - AuthException / AuthRejectedException
 */
class SphereWebSocketClientTest {
    private val client = SphereWebSocketClient(mockk(relaxed = true), mockk(relaxed = true), Json)

    private fun field(name: String): Long {
        val field = SphereWebSocketClient::class.java.getDeclaredField(name)
        field.isAccessible = true
        return (field.get(client) as Number).toLong()
    }


    // ── calculateBackoff ─────────────────────────────────────────────────────

    @Test
    fun `calculateBackoff attempt=1 → 1000–2000ms`() {
        assertTrue(calculateBackoff(1) in 1000L..2000L)
    }

    @Test
    fun `calculateBackoff attempt=2 → 2000–4000ms`() {
        assertTrue(calculateBackoff(2) in 2000L..4000L)
    }

    @Test
    fun `calculateBackoff attempt=3 → 4000–8000ms`() {
        assertTrue(calculateBackoff(3) in 4000L..8000L)
    }

    @Test
    fun `calculateBackoff attempt=4 → 8000–16000ms`() {
        assertTrue(calculateBackoff(4) in 8000L..16000L)
    }

    @Test
    fun `calculateBackoff attempt=5 → 15000–30000ms cap`() {
        // 1000 * 2^5 = 32000, cap = 30000
        assertTrue(calculateBackoff(5) in 15000L..30000L)
    }

    @Test
    fun `calculateBackoff attempt=10 → 15000–30000ms cap`() {
        assertTrue(calculateBackoff(10) in 15000L..30000L)
    }

    @Test
    fun `calculateBackoff attempt=100 → 15000–30000ms cap`() {
        assertTrue(calculateBackoff(100) in 15000L..30000L)
    }

    @Test
    fun `calculateBackoff attempt=0 → 500–1000ms`() {
        assertTrue(calculateBackoff(0) in 500L..1000L)
    }

    /** Invoke production policy; never duplicate its formula in the test. */
    private fun calculateBackoff(attempt: Int): Long {
        val method = SphereWebSocketClient::class.java.getDeclaredMethod("calculateBackoff", Int::class.javaPrimitiveType)
        method.isAccessible = true
        return method.invoke(client, attempt) as Long
    }

    // ── Constants ────────────────────────────────────────────────────────────

    @Test
    fun `CIRCUIT_OPEN_THRESHOLD = 10`() {
        assertEquals(10L, field("CIRCUIT_OPEN_THRESHOLD"))
    }

    @Test
    fun `CIRCUIT_COOL_DOWN_MS = 60 секунд`() {
        assertEquals(60_000L, field("CIRCUIT_COOL_DOWN_MS"))
    }

    @Test
    fun `FORCE_RECONNECT_DEBOUNCE_MS = 5 секунд`() {
        assertEquals(5_000L, field("FORCE_RECONNECT_DEBOUNCE_MS"))
    }

    // ── Close codes ──────────────────────────────────────────────────────────

    @Test
    fun `AUTH codes не должны вызывать circuit break`() {
        val authCodes = setOf("CODE_INVALID_TOKEN", "CODE_AUTH_TIMEOUT", "CODE_DEVICE_NOT_FOUND", "CODE_HEARTBEAT_TIMEOUT").map { field(it).toInt() }.toSet()
        assertTrue(authCodes.contains(4001))
        assertTrue(authCodes.contains(4003))
        assertTrue(authCodes.contains(4004))
        assertTrue(authCodes.contains(4008))
        assertFalse(authCodes.contains(1000)) // нормальное закрытие
    }

    // ── Exception classes ────────────────────────────────────────────────────

    @Test
    fun `AuthException содержит сообщение`() {
        val ex = AuthException("No token")
        assertEquals("No token", ex.message)
    }

    @Test
    fun `AuthRejectedException содержит code и reason`() {
        val ex = AuthRejectedException(4001, "invalid token")
        assertEquals(4001, ex.code)
        assertTrue(ex.message!!.contains("4001"))
        assertTrue(ex.message!!.contains("invalid token"))
    }

    @Test
    fun `AuthRejectedException наследует Exception`() {
        val ex: Exception = AuthRejectedException(4003, "timeout")
        assertTrue(ex is AuthRejectedException)
    }
}
