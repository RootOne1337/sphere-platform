package com.sphereplatform.agent.lua

import kotlinx.coroutines.withTimeout

/**
 * Запускает Lua-код с таймаутом 30 секунд.
 *
 * При превышении бросает [kotlinx.coroutines.TimeoutCancellationException],
 * которую [com.sphereplatform.agent.commands.DagRunner] перехватывает
 * и возвращает как "failed" ACK.
 */
suspend fun LuaEngine.executeWithTimeout(
    code: String,
    ctx: Map<String, Any?>,
    timeoutMs: Long = 30_000L,
): Any? = withTimeout(timeoutMs) {
    execute(code, ctx)
}
