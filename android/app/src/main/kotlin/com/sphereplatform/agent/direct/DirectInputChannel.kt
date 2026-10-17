package com.sphereplatform.agent.direct

import com.sphereplatform.agent.streaming.CaptureInputSession
import kotlinx.serialization.json.JsonObject

/** An existing authenticated peer is a transport, never authority to open native input. */
interface DirectInputChannel {
    val keyboardSupported: Boolean get() = false
    val session: String
    val capture: CaptureInputSession
    fun isCurrent(): Boolean
    fun send(message: JsonObject): Boolean
}

interface DirectInputHandler {
    fun directMessage(session: String, message: JsonObject): Boolean
    fun directClosed(session: String)
    /** Called only for server-authorized v2 control on this same media peer. */
    fun sharedGranted(channel: DirectInputChannel): Boolean = false
}
