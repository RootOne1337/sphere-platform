package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*

/** Server-authenticated, finite relay configuration; never a command or a media grant. */
class DirectProbeTurnGrant private constructor(
    val urls: List<String>, val username: String, val credential: String, val relayOnly: Boolean,
) {
    companion object {
        fun parse(value: JsonElement?, session: String): DirectProbeTurnGrant? {
            if (!DirectProbeProtocol.validSession(session)) return null
            val data = value as? JsonObject ?: return null
            if (data.keys != setOf("urls", "username", "credential", "ttl_ms", "policy")) return null
            val array = data["urls"] as? JsonArray ?: return null
            if (array.size !in 1..3) return null
            val urls = array.map {
                val item = it as? JsonPrimitive ?: return null
                if (!item.isString) return null
                item.content
            }
            if (urls.distinct().size != urls.size || urls.any { !validUrl(it) }) return null
            val username = data["username"] as? JsonPrimitive ?: return null
            val credential = data["credential"] as? JsonPrimitive ?: return null
            val policy = data["policy"] as? JsonPrimitive ?: return null
            val ttl = data["ttl_ms"] as? JsonPrimitive ?: return null
            if (!username.isString || !Regex("[1-9][0-9]{9}:$session:agent").matches(username.content) ||
                !credential.isString || !Regex("[A-Za-z0-9+/]{27}=").matches(credential.content) ||
                !policy.isString || policy.content !in setOf("all", "relay") || ttl.isString || ttl.intOrNull != 120000) return null
            return DirectProbeTurnGrant(urls, username.content, credential.content, policy.content == "relay")
        }

        fun validUrl(value: String): Boolean {
            if (value.length > 320) return false
            val match = Regex("(turn|turns):([a-z0-9.-]{1,253}):([1-9][0-9]{0,4})\\?transport=(udp|tcp)").matchEntire(value) ?: return false
            val (scheme, host, port, transport) = match.destructured
            if (port.toInt() > 65535 || scheme == "turns" && transport != "tcp") return false
            val parts = host.split('.')
            if (Regex("[0-9.]+").matches(host)) {
                if (parts.size != 4 || parts.any { !Regex("0|[1-9][0-9]{0,2}").matches(it) || it.toInt() > 255 }) return false
                val first = parts[0].toInt()
                return first != 0 && first != 127 && first < 224 && !(first == 169 && parts[1] == "254")
            }
            return parts.size >= 2 && Regex("[a-z][a-z0-9-]*").matches(parts.last()) && parts.all {
                Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?").matches(it)
            }
        }
    }
}
