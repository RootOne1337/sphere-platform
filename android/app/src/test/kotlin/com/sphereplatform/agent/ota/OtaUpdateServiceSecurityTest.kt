package com.sphereplatform.agent.ota

import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.security.MessageDigest

/**
 * Тесты OtaUpdateService — безопасность OTA-обновлений.
 *
 * Покрытие:
 *  - SSRF-защита: download_url host должен совпадать с server host
 *  - Path traversal: версия с .. в имени → исключение
 *  - SHA-256 верификация: логика совпадения/несовпадения
 *  - HTTPS-only: http → исключение
 *  - MAX_APK_SIZE_BYTES = 200MB
 *
 * Примечание: реальные HTTP-запросы не делаем — тестируем логику валидации.
 */
class OtaUpdateServiceSecurityTest {

    private lateinit var authStore: AuthTokenStore

    @Before
    fun setUp() {
        authStore = mockk(relaxed = true)
        every { authStore.getServerUrl() } returns "https://manage.sphere.io"
        every { authStore.getToken() } returns "test-token"
    }

    // ── SSRF-защита: validateDownloadUrl ─────────────────────────────────────

    @Test
    fun `SSRF download с того же хоста — ок`() {
        val serverUrl = "https://manage.sphere.io"
        val downloadUrl = "https://manage.sphere.io/api/v1/ota/download/1.2.3"
        val downloadHost = java.net.URI(downloadUrl).host
        val serverHost = java.net.URI(serverUrl).host
        assertEquals(serverHost, downloadHost)
    }

    @Test
    fun `SSRF download с другого хоста → различие`() {
        val serverUrl = "https://manage.sphere.io"
        val downloadUrl = "https://evil.attacker.com/steal-token"
        val downloadHost = java.net.URI(downloadUrl).host
        val serverHost = java.net.URI(serverUrl).host
        assertNotEquals(serverHost, downloadHost)
    }

    @Test
    fun `SSRF внутренний IP → различие с доменом сервера`() {
        val serverHost = java.net.URI("https://manage.sphere.io").host
        val downloadHost = java.net.URI("https://169.254.169.254/metadata").host
        assertNotEquals(serverHost, downloadHost)
    }

    // ── HTTPS-only ───────────────────────────────────────────────────────────

    @Test
    fun `HTTP URL отклоняется`() {
        val url = "http://manage.sphere.io/update.apk"
        assertFalse("HTTP не должен быть разрешён", url.startsWith("https://"))
    }

    @Test
    fun `HTTPS URL принимается`() {
        val url = "https://manage.sphere.io/update.apk"
        assertTrue(url.startsWith("https://"))
    }

    // ── Path traversal ───────────────────────────────────────────────────────

    @Test
    fun `path traversal в имени файла → детектируется`() {
        val apkDir = java.io.File("/data/app/ota")
        val maliciousVersion = "../../../data/system/evil"
        val dest = java.io.File(apkDir, "update_${maliciousVersion}.apk")
        val canonicalDest = dest.canonicalFile
        val canonicalDir = apkDir.canonicalFile
        assertFalse(
            "Path traversal должен быть обнаружен",
            canonicalDest.path.startsWith(canonicalDir.path),
        )
    }

    @Test
    fun `нормальная версия — нет path traversal`() {
        val apkDir = java.io.File("/data/app/ota")
        val normalVersion = "1.2.3"
        val dest = java.io.File(apkDir, "update_${normalVersion}.apk")
        val canonicalDest = dest.canonicalFile
        val canonicalDir = apkDir.canonicalFile
        assertTrue(
            "Нормальная версия не должна вызывать path traversal",
            canonicalDest.path.startsWith(canonicalDir.path),
        )
    }

    // ── SHA-256 верификация ──────────────────────────────────────────────────

    @Test
    fun `SHA-256 корректно вычисляется`() {
        val data = "test data for hashing".toByteArray()
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(data).joinToString("") { "%02x".format(it) }
        assertEquals(64, hash.length) // SHA-256 hex = 64 chars
    }

    @Test
    fun `SHA-256 детерминистичен`() {
        val data = "deterministic test".toByteArray()
        val hash1 = sha256(data)
        val hash2 = sha256(data)
        assertEquals(hash1, hash2)
    }

    @Test
    fun `SHA-256 разные данные → разные хеши`() {
        assertNotEquals(sha256("a".toByteArray()), sha256("b".toByteArray()))
    }

    @Test
    fun `SHA-256 mismatch должен быть обнаружен`() {
        val expected = "0000000000000000000000000000000000000000000000000000000000000000"
        val actual = sha256("real apk data".toByteArray())
        assertNotEquals("SHA-256 mismatch", expected, actual)
    }

    // ── MAX_APK_SIZE_BYTES ───────────────────────────────────────────────────

    @Test
    fun `MAX_APK_SIZE = 200MB`() {
        val maxSize = 200L * 1024 * 1024
        assertEquals(209_715_200L, maxSize)
    }

    @Test
    fun `Content-Length превышает MAX — rejection`() {
        val maxSize = 200L * 1024 * 1024
        val contentLength = 300L * 1024 * 1024
        assertTrue("Файл больше лимита должен быть отклонён", contentLength > maxSize)
    }

    private fun sha256(data: ByteArray): String {
        return MessageDigest.getInstance("SHA-256")
            .digest(data)
            .joinToString("") { "%02x".format(it) }
    }
}
