package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DirectProbeTurnGrantTest {
    private val session = "a".repeat(32)
    private fun wire() = buildJsonObject {
        put("urls", buildJsonArray { add("turn:192.168.1.5:3478?transport=udp"); add("turns:relay.example.test:443?transport=tcp") })
        put("username", "1791605120:$session:agent")
        put("credential", "A".repeat(27) + "=")
        put("ttl_ms", 120000); put("policy", "relay")
    }

    @Test fun serverGrantIsBoundToAgentSessionAndRelayPolicy() {
        val grant = DirectProbeTurnGrant.parse(wire(), session)!!
        assertTrue(grant.relayOnly)
        assertEquals(2, grant.urls.size)
        assertFalse(grant.toString().contains(grant.credential))
        assertNull(DirectProbeTurnGrant.parse(wire(), "b".repeat(32)))
        assertNull(DirectProbeTurnGrant.parse(wire(), session + "\n"))
    }

    @Test fun malformedOrBrowserGrantsCannotCreateNativeResources() {
        for ((key, value) in listOf(
            "username" to JsonPrimitive("1791605120:$session:browser"),
            "ttl_ms" to JsonPrimitive(true), "ttl_ms" to JsonPrimitive("120000"),
            "ttl_ms" to JsonPrimitive(120001), "policy" to JsonPrimitive("any"),
            "credential" to JsonPrimitive("x".repeat(10000)), "tap" to JsonPrimitive(1),
            "urls" to buildJsonArray {},
            "urls" to buildJsonArray { add("turn:192.168.1.5:3478?transport=udp"); add("turn:192.168.1.5:3478?transport=udp") },
        )) assertNull("key=$key", DirectProbeTurnGrant.parse(JsonObject(wire() + (key to value)), session))
        assertNull(DirectProbeTurnGrant.parse(JsonNull, session))
    }

    @Test fun canonicalUrlsMatchTheServerAndBrowserContract() {
        for (url in listOf("turn:192.168.1.5:3478?transport=udp", "turn:relay.example.test:3478?transport=tcp",
            "turns:relay.example.test:443?transport=tcp")) assertTrue(url, DirectProbeTurnGrant.validUrl(url))
        for (url in listOf("turn:127.0.0.1:3478?transport=udp", "turn:0.1.2.3:3478?transport=udp",
            "turn:224.0.0.1:3478?transport=udp", "turn:240.0.0.1:3478?transport=udp",
            "turn:169.254.1.1:3478?transport=udp", "turn:0172.16.1.2:3478?transport=udp",
            "turn:256.1.2.3:3478?transport=udp", "turn:relay.example.test:03478?transport=udp",
            "turn:relay.example.test:65536?transport=udp", "turn:relay.example.test:0?transport=udp",
            "turns:relay.example.test:443?transport=udp", "turn:user@relay.example.test:3478?transport=udp",
            "turn:relay.example.test:3478/path?transport=udp", "turn:relay.example.test:3478?transport=udp\n",
            "turn:RELAY.example.test:3478?transport=udp", "turn:relay.example.test:3478?transport=udp&credential=secret",
            "turn:[::1]:3478?transport=udp", "turn:relay:3478?transport=udp",
            "turn:" + "a".repeat(64) + ".test:3478?transport=udp")) assertFalse(url, DirectProbeTurnGrant.validUrl(url))
    }
}
