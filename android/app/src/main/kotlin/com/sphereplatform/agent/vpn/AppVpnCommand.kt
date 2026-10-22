package com.sphereplatform.agent.vpn

import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/** Own-UID IPC only. Never log the request or a parser exception. */
internal class AppVpnCommand private constructor(
    val requestId: UUID, val sessionId: UUID, val action: String,
    val profileRevisionId: UUID?, private val profile: JsonObject?,
) {
    override fun toString() = "AppVpnCommand(requestId=$requestId, sessionId=$sessionId, action=$action, profile=[redacted])"
    fun prepare(ownPackage: String, ownerUid: Int, source: AppIdentitySource): PreparedAppScopedConfig {
        val config = profile ?: throw VpnPreparationException("vpn_profile_required")
        val policy = config["traffic_policy"] as JsonObject
        val apps = AppTrafficSelectionResolver.resolve(AppTrafficSelection(
            policy["included_packages"]?.jsonArray?.map { it.jsonPrimitive.content } ?: emptyList(),
            mode = policy.getValue("mode").jsonPrimitive.content,
            controlPlane = policy.getValue("control_plane").jsonPrimitive.content,
            killSwitch = policy.getValue("kill_switch").jsonPrimitive.content,
            ipv6 = policy.getValue("ipv6").jsonPrimitive.content,
        ), ownPackage, ownerUid, source, android.os.Build.VERSION.SDK_INT)
        return AppScopedConfigPreparation.prepare(config.getValue("config_text").jsonPrimitive.content,
            config.getValue("protocol").jsonPrimitive.content, config.getValue("protocol_version").jsonPrimitive.content, apps)
    }
    companion object {
        private fun id(value: String) = UUID.fromString(value).also { require(it.toString() == value) }
        fun parse(text: String): AppVpnCommand {
            try {
                require(text.toByteArray(Charsets.UTF_8).size in 1..98304)
                val body = Json.parseToJsonElement(text) as JsonObject
                require(body.keys == setOf("schema_version", "request_id", "session_id", "action") || body.keys == setOf("schema_version", "request_id", "session_id", "action", "profile_revision_id", "profile"))
                val version = (body["schema_version"] as? JsonPrimitive)?.takeUnless { it.isString }?.intOrNull
                require(version in setOf(1, 2))
                val action = body.getValue("action").jsonPrimitive.content
                require(action in setOf("apply", "pause", "resume", "disconnect", "status", "rotate"))
                val profile = body["profile"] as? JsonObject
                require((action in setOf("apply", "rotate")) == (profile != null))
                if (profile != null) {
                    require(profile.keys == setOf("protocol", "protocol_version", "config_text", "traffic_policy"))
                    val policy = profile.getValue("traffic_policy") as JsonObject
                    val mode = policy.getValue("mode").jsonPrimitive.content
                    if (version == 2) {
                        require(mode == "all_apps_except_control")
                        require(policy.keys == setOf("mode", "control_plane", "kill_switch", "ipv6"))
                    } else {
                        require(mode == "selected_apps")
                        require(policy.keys == setOf("mode", "included_packages", "control_plane", "kill_switch", "ipv6"))
                        require(policy.getValue("included_packages").jsonArray.size in 1..64)
                    }
                    require(policy.getValue("control_plane").jsonPrimitive.content == "bypass")
                    require(policy.getValue("kill_switch").jsonPrimitive.content == mode)
                    require(policy.getValue("ipv6").jsonPrimitive.content in setOf("block", "tunnel"))
                } else require(version == 1)
                return AppVpnCommand(id(body.getValue("request_id").jsonPrimitive.content), id(body.getValue("session_id").jsonPrimitive.content), action,
                    body["profile_revision_id"]?.jsonPrimitive?.content?.let(::id), profile)
            } catch (_: Exception) { throw VpnPreparationException("vpn_ipc_request_invalid") }
        }
    }
}

@Serializable
internal data class AppVpnSnapshot(
    val requestId: String? = null,
    val sessionId: String? = null,
    val profileRevisionId: String? = null,
    val phase: String = "IDLE",
    val reason: String? = null,
    val nativeVersion: String? = null,
    val handshakeEpochSeconds: Long? = null,
    val rxBytes: Long? = null,
    val txBytes: Long? = null,
    val sampledAtEpochMs: Long = System.currentTimeMillis(),
    val providerPid: Int = android.os.Process.myPid(),
    val trafficMode: String? = null,
)

/** Process identity and sample time must be explicit on the wire. Omitting
 * defaults would reconstruct them in the management process at receive time.
 */
internal object AppVpnWire {
    val json = Json { encodeDefaults = true }
}
