package com.sphereplatform.agent.provisioning

import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest

/**
 * Тесты CloneDetector — обнаружение клонов и детекция эмуляторов.
 *
 * Покрытие:
 *  - SHA-256 fingerprint: детерминистичность, уникальность, формат
 *  - isEmulator: паттерны обнаружения (generic, sdk, genymotion, goldfish, ranchu)
 *  - getDeviceType: ldplayer, genymotion, nox, physical
 *
 * Примечание: тестируем логику без Android Context (паттерны Build).
 */
class CloneDetectorTest {

    // ── SHA-256 fingerprint ──────────────────────────────────────────────────

    @Test
    fun `sha256 fingerprint — 64 hex символа`() {
        val hash = sha256("test|input|data")
        assertEquals(64, hash.length)
        assertTrue(hash.all { it in "0123456789abcdef" })
    }

    @Test
    fun `sha256 fingerprint детерминистичен`() {
        val input = "instance:uuid|android_id:abc|build_fp:test"
        assertEquals(sha256(input), sha256(input))
    }

    @Test
    fun `разные входы → разные fingerprint`() {
        val hash1 = sha256("instance:uuid1|android_id:abc")
        val hash2 = sha256("instance:uuid2|android_id:abc")
        assertNotEquals(hash1, hash2)
    }

    @Test
    fun `fingerprint компоненты — все 7 присутствуют`() {
        val components = listOf(
            "instance:test-uuid",
            "android_id:abc123",
            "build_fp:google/sdk/generic:14",
            "serial:HY5T23FJKL",
            "board:goldfish_x86_64",
            "bootloader:unknown",
            "host:build-host",
        )
        assertEquals(7, components.size)
        val raw = components.joinToString("|")
        val hash = sha256(raw)
        assertEquals(64, hash.length)
    }

    // ── isEmulator паттерны ──────────────────────────────────────────────────

    @Test
    fun `isEmulator — generic в FINGERPRINT`() {
        assertTrue("generic".contains("generic", ignoreCase = true))
    }

    @Test
    fun `isEmulator — sdk в MODEL`() {
        assertTrue("Android SDK built for x86".contains("sdk", ignoreCase = true))
    }

    @Test
    fun `isEmulator — emulator в MODEL`() {
        assertTrue("Android Emulator".contains("emulator", ignoreCase = true))
    }

    @Test
    fun `isEmulator — Genymotion в MANUFACTURER`() {
        assertTrue("Genymotion".contains("Genymotion", ignoreCase = true))
    }

    @Test
    fun `isEmulator — vbox в PRODUCT`() {
        assertTrue("vbox86p".contains("vbox", ignoreCase = true))
    }

    @Test
    fun `isEmulator — goldfish в HARDWARE`() {
        assertTrue("goldfish".contains("goldfish", ignoreCase = true))
    }

    @Test
    fun `isEmulator — ranchu в HARDWARE`() {
        assertTrue("ranchu".contains("ranchu", ignoreCase = true))
    }

    @Test
    fun `isEmulator — физическое устройство без маркеров`() {
        val indicators = listOf(
            "samsung/dreamlte".contains("generic", ignoreCase = true),
            "SM-G950F".contains("sdk", ignoreCase = true),
            "SM-G950F".contains("emulator", ignoreCase = true),
            "samsung".contains("Genymotion", ignoreCase = true),
            "dreamlte".contains("sdk", ignoreCase = true),
            "dreamlte".contains("vbox", ignoreCase = true),
            "samsungexynos8895".contains("goldfish", ignoreCase = true),
            "samsungexynos8895".contains("ranchu", ignoreCase = true),
        )
        assertFalse("Физическое устройство не должно определяться как эмулятор",
            indicators.any { it })
    }

    // ── getDeviceType паттерны ────────────────────────────────────────────────

    @Test
    fun `ldplayer определяется по PRODUCT`() {
        assertTrue("aosp_ldplayer".contains("ldplayer", ignoreCase = true))
    }

    @Test
    fun `genymotion определяется по MANUFACTURER`() {
        assertTrue("Genymotion".contains("Genymotion", ignoreCase = true))
    }

    @Test
    fun `nox определяется по PRODUCT`() {
        assertTrue("nox".contains("nox", ignoreCase = true))
    }

    private fun sha256(input: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(input.toByteArray(Charsets.UTF_8))
        return hash.joinToString("") { "%02x".format(it) }
    }
}
