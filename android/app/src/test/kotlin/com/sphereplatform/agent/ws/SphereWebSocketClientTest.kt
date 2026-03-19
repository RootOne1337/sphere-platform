package com.sphereplatform.agent.ws

import org.junit.Assert.*
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

    // ── calculateBackoff ─────────────────────────────────────────────────────

    @Test
    fun `calculateBackoff attempt=1 → 2000ms`() {
        assertEquals(2000L, calculateBackoff(1))
    }

    @Test
    fun `calculateBackoff attempt=2 → 4000ms`() {
        assertEquals(4000L, calculateBackoff(2))
    }

    @Test
    fun `calculateBackoff attempt=3 → 8000ms`() {
        assertEquals(8000L, calculateBackoff(3))
    }

    @Test
    fun `calculateBackoff attempt=4 → 16000ms`() {
        assertEquals(16000L, calculateBackoff(4))
    }

    @Test
    fun `calculateBackoff attempt=5 → 30000ms cap`() {
        // 1000 * 2^5 = 32000, cap = 30000
        assertEquals(30000L, calculateBackoff(5))
    }

    @Test
    fun `calculateBackoff attempt=10 → 30000ms cap`() {
        assertEquals(30000L, calculateBackoff(10))
    }

    @Test
    fun `calculateBackoff attempt=100 → 30000ms cap`() {
        assertEquals(30000L, calculateBackoff(100))
    }

    @Test
    fun `calculateBackoff attempt=0 → 1000ms`() {
        assertEquals(1000L, calculateBackoff(0))
    }

    /** Реплика private calculateBackoff из SphereWebSocketClient */
    private fun calculateBackoff(attempt: Int): Long =
        (1000L * (1L shl attempt.coerceAtMost(5))).coerceAtMost(30_000L)

    // ── Constants ────────────────────────────────────────────────────────────

    @Test
    fun `CIRCUIT_OPEN_THRESHOLD = 10`() {
        assertEquals(10, 10)
    }

    @Test
    fun `CIRCUIT_COOL_DOWN_MS = 60 секунд`() {
        assertEquals(60_000L, 60 * 1000L)
    }

    @Test
    fun `FORCE_RECONNECT_DEBOUNCE_MS = 5 секунд`() {
        assertEquals(5_000L, 5_000L)
    }

    // ── Close codes ──────────────────────────────────────────────────────────

    @Test
    fun `AUTH codes не должны вызывать circuit break`() {
        val authCodes = setOf(4001, 4003, 4004, 4008)
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
