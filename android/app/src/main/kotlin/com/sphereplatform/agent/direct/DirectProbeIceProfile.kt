package com.sphereplatform.agent.direct

/** A diagnostic build setting, never an endpoint supplied by a viewer or signaling message. */
data class DirectProbeIceProfile(val name: String, val serverUrl: String?) {
    companion object {
        fun fromUrl(url: String): DirectProbeIceProfile {
            if (url.isEmpty()) return DirectProbeIceProfile("host", null)
            if (url == "stun:stun.cloudflare.com:3478") return DirectProbeIceProfile("public-stun", url)
            val match = Regex("^stun:([0-9.]+):([0-9]+)$").matchEntire(url)
                ?: throw IllegalArgumentException("invalid_controlled_stun")
            val parts = match.groupValues[1].split('.')
            require(parts.size == 4 && parts.all {
                Regex("^(0|[1-9][0-9]{0,2})$").matches(it) && it.toInt() <= 255
            }) { "invalid_controlled_stun" }
            val first = parts[0].toInt()
            val second = parts[1].toInt()
            val port = match.groupValues[2]
            require((first == 10 || first == 172 && second in 16..31 || first == 192 && second == 168) &&
                Regex("^[1-9][0-9]{3,4}$").matches(port) && port.toInt() in 1024..65535) {
                "invalid_controlled_stun"
            }
            return DirectProbeIceProfile("controlled-stun", url)
        }
    }
}
