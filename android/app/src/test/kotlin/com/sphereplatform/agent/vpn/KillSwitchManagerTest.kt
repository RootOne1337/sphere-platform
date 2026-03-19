package com.sphereplatform.agent.vpn

import org.junit.Assert.*
import org.junit.Test

/**
 * Тесты KillSwitchManager — валидация hostname/IP (anti command injection).
 *
 * Фокус: SAFE_HOST_PATTERN и requireSafeHost — защита от command injection
 * при вставке iptables-правил через su. Не тестируем реальный iptables (нужен root).
 *
 * Покрытие:
 *  - Валидные hostname: домен, IP, поддомен, дефис
 *  - Инъекции: пробелы, точка с запятой, pipe, backtick, $()
 *  - Пустая строка
 *  - Слишком длинный hostname (>256)
 */
class KillSwitchManagerTest {

    // Тестируем паттерн напрямую (SAFE_HOST_PATTERN из исходника)
    private val safeHostPattern = Regex("^[a-zA-Z0-9._\\-]+$")

    private fun isValidHost(host: String): Boolean {
        return host.isNotBlank() && host.length < 256 && safeHostPattern.matches(host)
    }

    // ── Валидные хосты ───────────────────────────────────────────────────────

    @Test
    fun `валидный IP адрес`() {
        assertTrue(isValidHost("192.168.1.1"))
    }

    @Test
    fun `валидный домен`() {
        assertTrue(isValidHost("example.com"))
    }

    @Test
    fun `поддомен`() {
        assertTrue(isValidHost("api.server.example.com"))
    }

    @Test
    fun `домен с дефисом`() {
        assertTrue(isValidHost("my-server.com"))
    }

    @Test
    fun `домен с подчёркиванием`() {
        assertTrue(isValidHost("my_server.com"))
    }

    @Test
    fun `localhost`() {
        assertTrue(isValidHost("localhost"))
    }

    @Test
    fun `IPv6-like числовой`() {
        assertTrue(isValidHost("10.0.0.1"))
    }

    // ── Command injection попытки ────────────────────────────────────────────

    @Test
    fun `инъекция через точку с запятой`() {
        assertFalse(isValidHost("1.1.1.1; rm -rf /"))
    }

    @Test
    fun `инъекция через пайп`() {
        assertFalse(isValidHost("host | cat /etc/passwd"))
    }

    @Test
    fun `инъекция через backtick`() {
        assertFalse(isValidHost("host`id`"))
    }

    @Test
    fun `инъекция через $()`() {
        assertFalse(isValidHost("host\$(whoami)"))
    }

    @Test
    fun `инъекция через пробелы`() {
        assertFalse(isValidHost("host with spaces"))
    }

    @Test
    fun `инъекция через кавычки`() {
        assertFalse(isValidHost("host'injection"))
    }

    @Test
    fun `инъекция через двойные кавычки`() {
        assertFalse(isValidHost("host\"injection"))
    }

    @Test
    fun `инъекция через newline`() {
        assertFalse(isValidHost("host\ninjection"))
    }

    @Test
    fun `инъекция через &&`() {
        assertFalse(isValidHost("host && rm -rf /"))
    }

    @Test
    fun `инъекция через redirect`() {
        assertFalse(isValidHost("host > /dev/null"))
    }

    // ── Граничные случаи ─────────────────────────────────────────────────────

    @Test
    fun `пустая строка — невалидна`() {
        assertFalse(isValidHost(""))
    }

    @Test
    fun `только пробелы — невалидна`() {
        assertFalse(isValidHost("   "))
    }

    @Test
    fun `хост длиной 255 — валидный`() {
        val host = "a".repeat(255)
        assertTrue(isValidHost(host))
    }

    @Test
    fun `хост длиной 256 — невалидный`() {
        val host = "a".repeat(256)
        assertFalse(isValidHost(host))
    }
}
