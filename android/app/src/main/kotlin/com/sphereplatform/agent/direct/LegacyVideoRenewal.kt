package com.sphereplatform.agent.direct

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

/** Optional paired fields; old renewals retain their exact contract. */
internal data class LegacyVideoRenewal(val enabled: Boolean, val ttlMs: Int) {
    companion object {
        val BASE_KEYS = setOf("type", "session_id", "sequence", "ttl_ms")
        val EXTENDED_KEYS = BASE_KEYS + setOf("legacy_video_enabled", "legacy_ttl_ms")
        fun parse(message: JsonObject): LegacyVideoRenewal? {
            if (message.keys != EXTENDED_KEYS) return null
            val enabled = message["legacy_video_enabled"] as? JsonPrimitive ?: return null
            val ttl = message["legacy_ttl_ms"] as? JsonPrimitive ?: return null
            if (enabled.isString || ttl.isString) return null
            val ttlMs = ttl.intOrNull?.takeIf { it in 1..10000 } ?: return null
            return LegacyVideoRenewal(enabled.booleanOrNull ?: return null, ttlMs)
        }
    }
}
