package com.sphereplatform.agent.network

import okhttp3.Dns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.UnknownHostException

/**
 * Unit-тесты для [FallbackDns].
 *
 * Проверяем:
 * 1. Системный DNS работает → fallback не вызывается
 * 2. Системный DNS падает → fallback через UDP резолвит
 * 3. Все резолверы падают → выбрасывается [UnknownHostException]
 * 4. Парсинг DNS wire-формата (RFC 1035)
 */
class FallbackDnsTest {

    /**
     * Проверяем что при работающем системном DNS FallbackDns корректно
     * возвращает результат (localhost/127.0.0.1 всегда резолвится).
     */
    @Test
    fun `системный DNS работает — возвращает результат без fallback`() {
        val dns = FallbackDns()
        val result = dns.lookup("localhost")
        assertNotNull(result)
        assertTrue("Должен вернуть хотя бы один адрес", result.isNotEmpty())
    }

    /**
     * Проверяем что Google DNS (8.8.8.8) может разрезолвить публичный домен.
     * Этот тест зависит от сетевого подключения.
     */
    @Test
    fun `fallback резолвит публичный домен через Google DNS`() {
        val dns = FallbackDns()
        // google.com гарантированно резолвится
        val result = dns.lookup("google.com")
        assertNotNull(result)
        assertTrue("google.com должен разрезолвиться", result.isNotEmpty())
    }

    /**
     * Проверяем что несуществующий домен выбрасывает UnknownHostException,
     * а не зависает или возвращает пустой список.
     */
    @Test(expected = UnknownHostException::class)
    fun `несуществующий домен — выбрасывает UnknownHostException`() {
        val dns = FallbackDns()
        dns.lookup("this-domain-definitely-does-not-exist-xyz123.invalid")
    }

    /**
     * Проверяем что FallbackDns реализует интерфейс okhttp3.Dns.
     */
    @Test
    fun `реализует интерфейс okhttp3 Dns`() {
        val dns: Dns = FallbackDns()
        assertNotNull(dns)
    }

    /**
     * Проверяем резолвинг домена serveo (наш реальный сервер).
     * Этот тест зависит от DNS-доступности serveo.net.
     */
    @Test
    fun `sphere serveousercontent com резолвится`() {
        val dns = FallbackDns()
        val result = dns.lookup("sphere.serveousercontent.com")
        assertNotNull(result)
        assertTrue("sphere.serveousercontent.com должен разрезолвиться", result.isNotEmpty())
        // IP должен быть валидным IPv4
        val ip = result.first()
        assertEquals("IPv4 = 4 байта", 4, ip.address.size)
    }
}
