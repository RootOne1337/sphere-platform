package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class LegacyVideoRenewalTest {
    private fun message(enabled: JsonElement = JsonPrimitive(false), ttl: JsonElement = JsonPrimitive(10000)) = buildJsonObject {
        put("type", "direct_probe_renew"); put("session_id", "a".repeat(32)); put("sequence", 1); put("ttl_ms", 30000)
        put("legacy_video_enabled", enabled); put("legacy_ttl_ms", ttl)
    }

    @Test fun pairedExtensionIsStrictAndBounded() {
        assertEquals(LegacyVideoRenewal(false, 10000), LegacyVideoRenewal.parse(message()))
        assertEquals(LegacyVideoRenewal(true, 1), LegacyVideoRenewal.parse(message(JsonPrimitive(true), JsonPrimitive(1))))
        for (ttl in listOf(JsonNull, JsonPrimitive("10000"), JsonPrimitive(0), JsonPrimitive(-1), JsonPrimitive(10001)))
            assertNull(LegacyVideoRenewal.parse(message(ttl=ttl)))
        for (enabled in listOf(JsonNull, JsonPrimitive("false"), JsonPrimitive(0)))
            assertNull(LegacyVideoRenewal.parse(message(enabled=enabled)))
        assertNull(LegacyVideoRenewal.parse(JsonObject(message() - "legacy_ttl_ms")))
        assertNull(LegacyVideoRenewal.parse(JsonObject(message() + ("command" to JsonPrimitive("tap")))))
    }
}
