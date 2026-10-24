package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class EmulatorHostCandidatesTest {
    private val name = "12345678-1234-4567-89ab-123456789abc.local"
    private fun candidate(address: String = name, protocol: String = "udp", type: String = "host", port: String = "45678") =
        "a=candidate:original 1 $protocol 2122260223 $address $port typ $type generation 0 ufrag unchanged"

    @Test fun `only recognized virtual guest addresses provide host hints`() {
        assertEquals(listOf("10.0.2.2", "10.0.3.2"), EmulatorHostCandidates.hints(listOf("10.0.2.15", "10.0.2.15", "10.0.3.15")))
        assertTrue(EmulatorHostCandidates.hints(listOf("127.0.0.1", "192.168.1.2", "10.0.2.2", "10.0.2.16", "::1")).isEmpty())
    }

    @Test fun `additional host hint preserves original candidate crypto ports and line endings`() {
        val prefix = "v=0\r\na=ice-pwd:unchanged-secret\r\na=fingerprint:unchanged\r\n"
        val source = prefix + candidate() + "\r\na=end-of-candidates\r\n"
        val result = EmulatorHostCandidates.augment(source, listOf("10.0.2.2"))
        assertEquals(1, result.added)
        assertTrue(result.sdp.startsWith(prefix + candidate() + "\r\n"))
        assertTrue(result.sdp.contains("1 udp 2122260222 10.0.2.2 45678 typ host generation 0 ufrag unchanged\r\n"))
        assertTrue(result.sdp.endsWith("a=end-of-candidates\r\n"))
        assertEquals(source, result.sdp.replace(Regex("a=candidate:spherehost[^\\r\\n]+\\r\\n"), ""))
    }

    @Test fun `LAN resolution retains an independent host local opportunity without replacing it`() {
        val source = candidate("192.168.43.8") + "\n"
        val result = EmulatorHostCandidates.augment(source, listOf("10.0.2.2"))
        assertEquals(1, result.added)
        assertTrue(result.sdp.startsWith(source))
        assertTrue(result.sdp.contains("10.0.2.2 45678"))
    }

    @Test fun `TCP public reflexive malformed and unrelated DNS candidates stay unchanged`() {
        val cases = listOf(candidate(protocol = "tcp"), candidate("8.8.8.8"), candidate(type = "srflx"),
            candidate("printer.local"), candidate(port = "0"), candidate(port = "65536"), candidate("10.999.1.2"),
            candidate().replace("2122260223", "4294967296"), candidate("::1"))
        for (source in cases) assertEquals(EmulatorHostCandidates.Result(source, 0), EmulatorHostCandidates.augment(source, listOf("10.0.2.2")))
        assertEquals(EmulatorHostCandidates.Result(candidate(), 0), EmulatorHostCandidates.augment(candidate(), listOf("127.0.0.1", "8.8.8.8", "0.0.0.0", "::1")))
    }

    @Test fun `bundle sections candidates and description size stay bounded`() {
        val source = List(20) { candidate() }.joinToString("\r\n", postfix = "\r\n")
        val result = EmulatorHostCandidates.augment(source, listOf("10.0.2.2", "10.0.3.2", "10.0.2.2"))
        assertEquals(8, result.added)
        assertEquals(28, result.sdp.lineSequence().count { it.startsWith("a=candidate:") })
        val full = List(64) { candidate() }.joinToString("\n")
        assertEquals(EmulatorHostCandidates.Result(full, 0), EmulatorHostCandidates.augment(full, listOf("10.0.2.2")))
        val oversized = "x".repeat(32768) + candidate()
        assertEquals(EmulatorHostCandidates.Result(oversized, 0), EmulatorHostCandidates.augment(oversized, listOf("10.0.2.2")))
    }

    @Test fun `description without newline or an already identical alias retains valid candidate lines`() {
        val result = EmulatorHostCandidates.augment(candidate(), listOf("10.0.2.2", "10.0.3.2"))
        assertEquals(2, result.added)
        assertEquals(3, result.sdp.lines().size)
        val same = candidate("10.0.2.2")
        assertEquals(EmulatorHostCandidates.Result(same, 0), EmulatorHostCandidates.augment(same, listOf("10.0.2.2")))
    }

    @Test fun `nonstandard x86 guest uses only actual private default gateways`() {
        val hints = EmulatorHostCandidates.hints(listOf("192.168.232.101"),
            listOf("192.168.232.2", "192.168.232.2", "8.8.8.8", "127.0.0.1"), x86Guest = true)
        assertEquals(listOf("192.168.232.2"), hints)
        val result = EmulatorHostCandidates.augment(candidate(), hints)
        assertEquals(1, result.added)
        assertTrue(result.sdp.contains("192.168.232.2 45678 typ host"))
    }

    @Test fun `ordinary ARM LAN gateway is not guessed to be the browser host`() {
        assertTrue(EmulatorHostCandidates.hints(listOf("192.168.1.5"), listOf("192.168.1.1"), x86Guest = false).isEmpty())
        assertTrue(EmulatorHostCandidates.hints(listOf("192.168.232.101"), emptyList(), x86Guest = true).isEmpty())
    }
}
