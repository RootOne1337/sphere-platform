package com.sphereplatform.agent.direct

/** Explicit read-only RTP experiment. The older echo permission cannot authorize video. */
object DirectVideoProtocol {
    const val MODE = "readonly_video_v1"
    const val LABEL = "sphere-video-probe-v1"
    const val MIN_VERSION_CODE = 10251

    fun validSdp(value: String, offer: Boolean): Boolean {
        if (value.toByteArray(Charsets.UTF_8).size !in 1..DirectProbeProtocol.MAX_SDP_BYTES) return false
        val lines = value.lines()
        val sections = mutableListOf<MutableList<String>>()
        lines.forEach { line ->
            if (line.startsWith("m=")) sections.add(mutableListOf(line))
            else sections.lastOrNull()?.add(line)
        }
        val application = sections.singleOrNull { it[0].startsWith("m=application ") } ?: return false
        val video = sections.singleOrNull { it[0].startsWith("m=video ") } ?: return false
        val fingerprints = lines.filter { it.startsWith("a=fingerprint:") }
        return lines.firstOrNull() == "v=0" && sections.size == 2 &&
            application[0].contains("UDP/DTLS/SCTP") && video[0].contains("UDP/TLS/RTP/SAVPF") &&
            video.count { it in setOf("a=sendrecv", "a=sendonly", "a=recvonly", "a=inactive") } == 1 &&
            (if (offer) "a=recvonly" else "a=sendonly") in video &&
            video.any { Regex("a=rtpmap:[0-9]+ H264/90000", RegexOption.IGNORE_CASE).matches(it) } &&
            fingerprints.size in 1..3 && fingerprints.all {
                Regex("a=fingerprint:sha-256 (?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}").matches(it)
            } && lines.count { it.startsWith("a=candidate:") } <= 64
    }
}
