package com.sphereplatform.agent.direct

/** Finite RTT echo only. This protocol cannot describe or execute an Android action. */
object DirectProbeProtocol {
    const val LABEL = "sphere-probe-v1"
    const val MAX_SDP_BYTES = 32768
    const val MAX_TTL_MS = 30000
    private val nonce = Regex("[0-9a-f]{32}")
    fun validSession(value: String) = nonce.matches(value)
    fun validSdp(value: String): Boolean {
        if (value.toByteArray(Charsets.UTF_8).size !in 1..MAX_SDP_BYTES) return false
        val lines = value.lines()
        val media = lines.filter { it.startsWith("m=") }
        val fingerprints = lines.filter { it.startsWith("a=fingerprint:") }
        return lines.firstOrNull() == "v=0" && media.size == 1 &&
            media[0].startsWith("m=application ") && media[0].contains("UDP/DTLS/SCTP") &&
            fingerprints.size in 1..2 && fingerprints.all {
                Regex("a=fingerprint:sha-256 (?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}").matches(it)
            } && lines.count { it.startsWith("a=candidate:") } <= 64
    }
    fun echo(text: String, session: String, expectedSequence: Int): String? {
        if (!validSession(session) || expectedSequence !in 1..64 || text.length > 80) return null
        return "SP1 $session $expectedSequence".takeIf { text == it }
    }
}
