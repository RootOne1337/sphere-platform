package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DirectIceCandidateTest {
    private fun wire(address: String = "192.168.1.20") = buildJsonObject {
        put("candidate", "candidate:1 1 udp 2122260223 $address 53000 typ host generation 0")
        put("sdpMid", "0"); put("sdpMLineIndex", 0)
    }
    @Test fun localReflexiveAndMdnsHintsRoundTripWithoutDiscovery() {
        for (address in listOf("192.168.1.20", "10.0.2.15", "2001:db8::1",
            "01234567-89ab-cdef-0123-456789abcdef.local")) {
            val value = wire(address)
            val fields = DirectIceCandidate.parse(value)!!
            assertEquals(value, DirectIceCandidate.wire(fields))
        }
    }
    @Test fun candidatesCannotSmuggleIdentityOrArbitraryDnsOrOversizedPayload() {
        for ((key, value) in listOf("sdpMid" to JsonPrimitive("../private"),
            "sdpMLineIndex" to JsonPrimitive(true), "sdpMLineIndex" to JsonPrimitive("0"),
            "sdpMLineIndex" to JsonPrimitive(8), "owner" to JsonPrimitive("other"),
            "candidate" to JsonPrimitive("x".repeat(2049)),
            "candidate" to JsonPrimitive("candidate:1 1 udp 1 192.168.1.20 53000 typ host\r\nx"))) {
            assertNull(key, DirectIceCandidate.parse(JsonObject(wire() + (key to value))))
        }
        assertNull(DirectIceCandidate.parse(wire("arbitrary.example.test")))
        assertNull(DirectIceCandidate.parse(wire("999.1.2.3")))
        assertNull(DirectIceCandidate.parse(JsonNull))
    }
}
