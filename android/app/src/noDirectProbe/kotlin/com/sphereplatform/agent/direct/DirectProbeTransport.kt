package com.sphereplatform.agent.direct

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/** No WebRTC JNI or native factory is shipped by the ordinary build. */
@Suppress("UNUSED_PARAMETER")
class DirectProbeTransport(
    context: Context, scope: CoroutineScope,
    generation: () -> Long?, send: (Long, JsonObject) -> Boolean,
) {
    fun handle(message: JsonObject) = message["type"]?.jsonPrimitive?.contentOrNull in
        setOf("direct_probe_offer", "direct_probe_close")
    fun invalidate() = Unit
}
