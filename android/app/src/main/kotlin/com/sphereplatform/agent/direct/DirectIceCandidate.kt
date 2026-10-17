package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*

/** Ephemeral authenticated signaling only; no candidate addresses in telemetry. */
internal object DirectIceCandidate {
    const val MAX = 64
    data class Fields(val candidate: String, val mid: String, val index: Int)
    fun parse(value: JsonElement?): Fields? {
        val obj = value as? JsonObject ?: return null
        if (obj.keys != setOf("candidate", "sdpMid", "sdpMLineIndex")) return null
        val raw = (obj["candidate"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val mid = (obj["sdpMid"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val index = (obj["sdpMLineIndex"] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull ?: return null
        if (raw.length !in 1..2048 || raw.any { it.code !in 32..126 } || index !in 0..7
            || !Regex("[A-Za-z0-9_-]{1,16}").matches(mid)) return null
        val f = raw.split(Regex(" +"))
        if (f.size !in 8..32 || !Regex("candidate:[A-Za-z0-9+/_-]{1,64}").matches(f[0])
            || f[1] !in setOf("1", "2") || !f[2].equals("udp", true)
            || f[3].toLongOrNull() !in 1..0xffff_ffffL || f[5].toIntOrNull() !in 1..65535
            || f[6] != "typ" || f[7] !in setOf("host", "srflx", "prflx")) return null
        val mdns = Regex("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\\.local").matches(f[4])
        val v4 = f[4].split('.').let { fields -> fields.size == 4 && fields.all {
            it.isNotEmpty() && it.length <= 3 && it.all(Char::isDigit) && it.toIntOrNull() in 0..255 } }
        val v6 = f[4].contains(':') && f[4].length <= 45 && f[4].all { it in "0123456789abcdefABCDEF:." }
        if (!mdns && !v4 && !v6) return null
        return Fields(raw, mid, index)
    }
    fun wire(fields: Fields): JsonObject = buildJsonObject {
        put("candidate", fields.candidate); put("sdpMid", fields.mid); put("sdpMLineIndex", fields.index)
    }
}
