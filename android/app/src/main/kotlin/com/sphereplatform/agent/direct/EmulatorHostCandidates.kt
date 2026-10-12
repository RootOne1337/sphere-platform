package com.sphereplatform.agent.direct

/**
 * Extra ICE hints for a standard emulator NAT's host adapter. They are candidates,
 * not proof that the viewer runs on this host. ICE authentication and DTLS still
 * have to succeed. Existing candidates, ports and session credentials stay intact.
 *
 * This avoids making a nearby central server's multicast DNS resolver a prerequisite
 * for trying the host-local route. It does not forward media or expose an HTTP service.
 */
internal object EmulatorHostCandidates {
    private const val MAX_ADDITIONS = 8
    private const val MAX_CANDIDATES = 64
    private val aliases = mapOf("10.0.2.15" to "10.0.2.2", "10.0.3.15" to "10.0.3.2")
    private val mdns = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.local")

    data class Result(val sdp: String, val added: Int)

    /** Recognized NAT pairs or an x86 guest's actual default gateway. No subnet scan. */
    fun hints(localAddresses: Iterable<String>, gateways: List<String> = emptyList(), x86Guest: Boolean = false): List<String> {
        val fixed = localAddresses.take(256).mapNotNull { aliases[it] }
        val discovered = if (x86Guest) gateways.take(8).filter { privateV4(it) } else emptyList()
        return (fixed + discovered).distinct().take(2)
    }

    fun augment(sdp: String, hints: List<String>): Result {
        // Hints come from local interface/route discovery, never a remote SDP field.
        val admitted = hints.filter { privateV4(it) }.distinct().take(2)
        if (admitted.isEmpty() || sdp.toByteArray(Charsets.UTF_8).size > DirectProbeProtocol.MAX_SDP_BYTES)
            return Result(sdp, 0)
        val lines = sdp.splitToSequence('\n').toList()
        val existing = lines.count { it.startsWith("a=candidate:") }
        if (existing >= MAX_CANDIDATES) return Result(sdp, 0)
        var added = 0
        val output = StringBuilder(sdp.length + 1024)
        lines.forEachIndexed { index, original ->
            output.append(original)
            val hasNewline = index < lines.lastIndex
            if (hasNewline) output.append('\n')
            val line = original.removeSuffix("\r")
            val fields = line.split(Regex("[ \\t]+"))
            if (fields.size >= 8 && fields[0].startsWith("a=candidate:") && fields[1] in setOf("1", "2") &&
                fields[2].equals("udp", ignoreCase = true) && fields.subList(6, 8) == listOf("typ", "host") &&
                (mdns.matches(fields[4]) || privateV4(fields[4])) && fields[5].toIntOrNull() in 1..65535) {
                val priority = fields[3].toLongOrNull()?.takeIf { it in 2..0xffff_ffffL }
                if (priority != null) for (address in admitted) {
                    if (address == fields[4] || added >= MAX_ADDITIONS || existing + added >= MAX_CANDIDATES) continue
                    val hint = fields.toMutableList()
                    hint[0] = "a=candidate:spherehost${index}a${added}"
                    hint[3] = (priority - 1).toString()
                    hint[4] = address
                    // Keep the original line ending, including an SDP without a final newline.
                    if (!hasNewline) output.append(if (original.endsWith('\r')) "\r\n" else "\n")
                    output.append(hint.joinToString(" "))
                    if (hasNewline) output.append(if (original.endsWith('\r')) "\r\n" else "\n")
                    added++
                }
            }
        }
        val result = output.toString()
        return if (result.toByteArray(Charsets.UTF_8).size <= DirectProbeProtocol.MAX_SDP_BYTES)
            Result(result, added) else Result(sdp, 0)
    }

    private fun privateV4(value: String): Boolean {
        val fields = value.split('.')
        if (fields.size != 4 || fields.any { it.isEmpty() || it.length > 3 || it.any { c -> c !in '0'..'9' } }) return false
        val bytes = fields.map { it.toIntOrNull()?.takeIf { byte -> byte in 0..255 } ?: return false }
        return bytes[0] == 10 || bytes[0] == 192 && bytes[1] == 168 || bytes[0] == 172 && bytes[1] in 16..31
    }
}
