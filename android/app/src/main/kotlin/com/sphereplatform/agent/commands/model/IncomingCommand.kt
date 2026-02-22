package com.sphereplatform.agent.commands.model

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class IncomingCommand(
    val command_id: String,
    val type: CommandType,
    val payload: JsonObject = JsonObject(emptyMap()),
    val signed_at: Long,           // UTC epoch seconds
    val ttl_seconds: Int = 60,
)

@Serializable
data class CommandAck(
    val command_id: String,
    val status: String,            // "received" | "running" | "completed" | "failed"
    val error: String? = null,
    val result: JsonObject? = null,
)
