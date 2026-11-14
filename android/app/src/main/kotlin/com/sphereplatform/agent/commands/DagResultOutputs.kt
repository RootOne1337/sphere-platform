package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private val contextKeyPattern = Regex("[A-Za-z_][A-Za-z0-9_-]{0,63}")
private val levelPattern = Regex("[0-9]{1,10}")

/** Allowlist typed values from a terminal end node's explicit context mappings. */
internal fun readDagResultOutputs(
    action: JsonObject,
    context: Map<String, Any?>,
    success: Boolean,
): JsonObject? {
    val outputs = action["result_outputs"] as? JsonObject ?: return null
    fun valueFor(name: String): Any? {
        val key = outputs[name] as? JsonPrimitive ?: return null
        return if (key.isString && contextKeyPattern.matches(key.content)) context[key.content] else null
    }
    return buildJsonObject {
        if (success) {
            val level = when (val value = valueFor("level")) {
                is Int -> value
                is Long -> value.toInt().takeIf { it.toLong() == value }
                is Double -> value.toInt().takeIf { it.toDouble() == value }
                is String -> value.takeIf(levelPattern::matches)?.toIntOrNull()
                else -> null
            }
            level?.takeIf { it >= 0 }?.let { put("level", it) }
        }
        when (valueFor("ban_detected")) {
            true, "true" -> put("ban_detected", true)
            false, "false" -> put("ban_detected", false)
        }
    }
}
