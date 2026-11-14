package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Fixed-size scalar window; no owners, coordinates, keys or input history. */
internal class SharedInputTiming {
    private val waits = LongArray(WINDOW)
    private val processing = LongArray(WINDOW)
    private val depths = IntArray(WINDOW)
    private var next = 0
    private var size = 0
    private var total = 0L

    @Synchronized fun record(waitMs: Long, processingMs: Long, pending: Int) {
        if (waitMs < 0 || processingMs < 0 || pending < 0) return
        waits[next] = waitMs.coerceAtMost(MAX_MS)
        processing[next] = processingMs.coerceAtMost(MAX_MS)
        depths[next] = pending.coerceAtMost(MAX_PENDING)
        next = (next + 1) % WINDOW
        size = (size + 1).coerceAtMost(WINDOW)
        total = (total + 1).coerceAtMost(9_007_199_254_740_992L)
    }

    @Synchronized fun snapshot(): JsonObject? {
        if (size == 0) return null
        val last = (next + WINDOW - 1) % WINDOW
        val sortedWaits = waits.copyOf(size).sortedArray()
        val sortedProcessing = processing.copyOf(size).sortedArray()
        val p95 = (size * 95 + 99) / 100 - 1
        return buildJsonObject {
            put("scope", "shared_actor")
            put("window_samples", size)
            put("samples_total", total)
            put("queue_wait_ms_last", waits[last])
            put("queue_wait_ms_max", sortedWaits.last())
            put("queue_wait_ms_p95", sortedWaits[p95])
            put("processing_ms_last", processing[last])
            put("processing_ms_max", sortedProcessing.last())
            put("processing_ms_p95", sortedProcessing[p95])
            put("pending_last", depths[last])
            put("pending_max", depths.take(size).max())
        }
    }

    private companion object {
        const val WINDOW = 128
        const val MAX_MS = 10_000L
        const val MAX_PENDING = SharedPointerArbiter.MAX_PARTICIPANTS *
            (SharedInputMailbox.PER_PARTICIPANT + SharedInputMailbox.KEYBOARD_PENDING)
    }
}
