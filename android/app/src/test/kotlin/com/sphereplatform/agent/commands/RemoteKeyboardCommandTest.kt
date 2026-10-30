package com.sphereplatform.agent.commands

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class RemoteKeyboardCommandTest {
    private fun message(op: String, text: String? = null) = buildJsonObject {
        put("type", "keyboard_event"); put("sequence", 1); put("operation", op); put("editor_generation", 4)
        if (text != null) put("text", text)
    }
    @Test fun `Unicode and emoji remain ephemeral and never appear in command string`() {
        val command = checkNotNull(RemoteKeyboardCommand.parse(message("commit", "Привет 🙂 你好")))
        assertEquals("Привет 🙂 你好", command.text)
        assertFalse(command.toString().contains("Привет"))
        assertNull(RemoteKeyboardCommand.parse(message("commit", "\uD800")))
        assertNull(RemoteKeyboardCommand.parse(message("commit", "a".repeat(1025))))
        assertNull(RemoteKeyboardCommand.parse(message("commit", "\u0000")))
        assertNull(RemoteKeyboardCommand.parse(message("commit", "")))
        assertNotNull(RemoteKeyboardCommand.parse(message("compose", "")))
    }
    @Test fun `exact fields and known operations exclude shell power and arbitrary meta bits`() {
        assertNull(RemoteKeyboardCommand.parse(message("shell")))
        assertNull(RemoteKeyboardCommand.parse(JsonObject(message("finish") + ("text" to JsonPrimitive("hidden")))))
        fun key(code: Int, meta: Int) = JsonObject(message("key_down") + mapOf("keycode" to JsonPrimitive(code), "meta" to JsonPrimitive(meta)))
        assertNotNull(RemoteKeyboardCommand.parse(key(29, 4097)))
        assertNull(RemoteKeyboardCommand.parse(key(26, 0)))
        assertNull(RemoteKeyboardCommand.parse(key(29, 0x80000000.toInt())))
        assertNull(RemoteKeyboardCommand.parse(key(29, 8)))
    }
}
