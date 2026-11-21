package com.sphereplatform.agent.commands

import kotlinx.serialization.json.*

/** Ephemeral input only: never included in diagnostics, logs, command history or receipts. */
internal data class RemoteKeyboardCommand(
    val operation: Operation, val editorGeneration: Long, val text: String? = null,
    val keyCode: Int = 0, val meta: Int = 0,
) {
    enum class Operation { COMMIT, COMPOSE, FINISH, DELETE_BACKWARD, DELETE_FORWARD, KEY_DOWN, KEY_UP, RESET }
    companion object {
        const val MAX_TEXT_UNITS = 1024
        const val ACTION = 9
        fun parse(value: JsonObject): RemoteKeyboardCommand? {
            val op = (value["operation"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?.let { raw -> Operation.entries.firstOrNull { it.name.lowercase() == raw } } ?: return null
            val generation = (value["editor_generation"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                ?.takeIf { it in 0..Int.MAX_VALUE.toLong() } ?: return null
            val base = setOf("type", "sequence", "operation", "editor_generation")
            val textOp = op in setOf(Operation.COMMIT, Operation.COMPOSE)
            val keyOp = op in setOf(Operation.KEY_DOWN, Operation.KEY_UP)
            if (value.keys != base + if (textOp) setOf("text") else if (keyOp) setOf("keycode", "meta") else emptySet()) return null
            val text = if (textOp) (value["text"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null else null
            if (text != null && (!validText(text) || op == Operation.COMMIT && text.isEmpty())) return null
            val code = if (keyOp) (value["keycode"] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull ?: return null else 0
            val meta = if (keyOp) (value["meta"] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull ?: return null else 0
            if (keyOp && (!RootTouchSession.supportedHardwareKey(code) || !RootTouchSession.supportedMeta(meta))) return null
            return RemoteKeyboardCommand(op, generation, text, code, meta)
        }
        fun validText(text: String): Boolean {
            if (text.length > MAX_TEXT_UNITS || text.any { it == '\u0000' || it < ' ' && it != '\n' && it != '\t' }) return false
            var i = 0
            while (i < text.length) {
                val c = text[i++]
                if (c.isHighSurrogate()) { if (i >= text.length || !text[i++].isLowSurrogate()) return false }
                else if (c.isLowSurrogate()) return false
            }
            return true
        }
    }
    // Prevent accidental string interpolation of typed input in an exception/log.
    override fun toString() = "RemoteKeyboardCommand(${operation.name})"
}

internal interface RemoteKeyboardAdapter {
    data class State(val enabled: Boolean, val editorGeneration: Long, val editorActive: Boolean)
    enum class Result { ACCEPTED, NO_EDITOR, STALE_EDITOR, UNAVAILABLE, UNKNOWN }
    suspend fun enable(owner: String): Boolean
    suspend fun disable(owner: String): Boolean
    suspend fun reset(): Boolean
    fun state(): State
    suspend fun apply(owner: String, command: RemoteKeyboardCommand, current: () -> Boolean): Result
    suspend fun release(owner: String): Boolean
}
