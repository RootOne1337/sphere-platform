package com.sphereplatform.agent.vpn

import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test

class AppVpnCommandTest {
    private val request = UUID.randomUUID().toString()
    private val session = "a4da36ab-4f76-4683-b79e-857fa69abcde"
    private fun body(action: String) = buildJsonObject {
        put("schema_version", 1); put("request_id", request); put("session_id", session); put("action", action)
    }
    @Test fun metadataActionsHaveNoProfileOrSecretSurface() {
        for (action in listOf("status", "pause", "resume", "disconnect")) {
            val parsed = AppVpnCommand.parse(body(action).toString())
            assertEquals(action, parsed.action); assertEquals(request, parsed.requestId.toString()); assertEquals(session, parsed.sessionId.toString())
        }
    }
    @Test fun errorsNeverEchoAnUntrustedRequestOrSecret() {
        val malformed = listOf("secret-sentinel", body("apply").toString(), body("shell").toString(),
            body("status").toString().replace(session, session.uppercase()),
            body("status").toString().dropLast(1) + ",\"config_text\":\"secret-sentinel\"}")
        for (text in malformed) {
            try { AppVpnCommand.parse(text); fail("Request accepted") }
            catch (failure: VpnPreparationException) { assertEquals("vpn_ipc_request_invalid", failure.message); assertNull(failure.cause) }
        }
    }
    @Test fun profilesRemainRedactedInTheCommandProjection() {
        val profile = Json.parseToJsonElement("""{"protocol":"wireguard","protocol_version":"1","config_text":"private-sentinel","traffic_policy":{"mode":"selected_apps","included_packages":["org.example.game"],"control_plane":"bypass","kill_switch":"selected_apps","ipv6":"block"}}""").jsonObject
        val command = buildJsonObject {
            body("apply").forEach { (key, value) -> put(key, value) }
            put("profile_revision_id", UUID.randomUUID().toString()); put("profile", profile)
        }
        val parsed = AppVpnCommand.parse(command.toString())
        assertFalse(parsed.toString().contains("private-sentinel"))
        assertFalse(parsed.toString().contains("config_text"))
    }
    @Test fun processIdentitySampleClockAndUnknownCountersAreExplicitAcrossProcesses() {
        val encoded = AppVpnWire.json.encodeToJsonElement(AppVpnSnapshot(providerPid = 321, sampledAtEpochMs = 1234)).jsonObject
        assertEquals("321", encoded.getValue("providerPid").jsonPrimitive.content)
        assertEquals("1234", encoded.getValue("sampledAtEpochMs").jsonPrimitive.content)
        assertEquals("null", encoded.getValue("rxBytes").toString())
        assertEquals("null", encoded.getValue("handshakeEpochSeconds").toString())
    }
}
