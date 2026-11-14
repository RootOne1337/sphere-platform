package com.sphereplatform.agent.direct

/** An offered lower receive level cannot authorize higher-level pre-encoded pictures. */
internal object AvcReceiveCapabilities {
    fun acceptsParameters(parameters: Map<String, String>, requiredProfile: String): Boolean {
        if (!Regex("42e0[0-9a-f]{2}").matches(requiredProfile) || parameters.size > 32) return false
        val params = parameters.mapKeys { it.key.lowercase() }.mapValues { it.value.lowercase() }
        val profile = params["profile-level-id"] ?: "42e01f"
        return params["packetization-mode"] == "1" && Regex("42[ec]0[0-9a-f]{2}").matches(profile) &&
            profile.takeLast(2).toInt(16) >= requiredProfile.takeLast(2).toInt(16)
    }

    fun accepts(sdp: String, requiredProfile: String): Boolean {
        if (!Regex("42e0[0-9a-f]{2}").matches(requiredProfile)) return false
        val h264 = Regex("(?im)^a=rtpmap:(\\d+) H264/90000\\r?$").findAll(sdp).map { it.groupValues[1] }.toSet()
        return Regex("(?m)^a=fmtp:(\\d+) ([^\\r\\n]+)").findAll(sdp).any { fmtp ->
            if (fmtp.groupValues[1] !in h264) return@any false
            val params = fmtp.groupValues[2].split(';').mapNotNull { value ->
                val parts = value.trim().split('=', limit = 2)
                if (parts.size == 2) parts[0].lowercase() to parts[1].lowercase() else null
            }.toMap()
            acceptsParameters(params, requiredProfile)
        }
    }
}
