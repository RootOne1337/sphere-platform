package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class SharedInputTimingTest {
    @Test fun `empty or regressed measurements do not invent latency`() {
        val timing = SharedInputTiming()
        assertNull(timing.snapshot())
        timing.record(-1, 5, 0); timing.record(5, -1, 0); timing.record(5, 1, -1)
        assertNull(timing.snapshot())
    }

    @Test fun `burst peak is retained while idle values do not replace action window`() {
        val timing = SharedInputTiming()
        timing.record(3, 7, 0)
        timing.record(180, 25, 2)
        timing.record(2, 6, 0)
        val snapshot = checkNotNull(timing.snapshot())
        assertEquals(JsonPrimitive(2L), snapshot["queue_wait_ms_last"])
        assertEquals(JsonPrimitive(180L), snapshot["queue_wait_ms_max"])
        assertEquals(JsonPrimitive(180L), snapshot["queue_wait_ms_p95"])
        assertEquals(JsonPrimitive(25L), snapshot["processing_ms_max"])
        assertEquals(JsonPrimitive(2), snapshot["pending_max"])
    }

    @Test fun `window evicts stale peaks and clamps counters without storing input`() {
        val timing = SharedInputTiming()
        timing.record(Long.MAX_VALUE, Long.MAX_VALUE, Int.MAX_VALUE)
        val clamped = checkNotNull(timing.snapshot())
        assertEquals(JsonPrimitive(10_000L), clamped["queue_wait_ms_max"])
        assertEquals(JsonPrimitive(360), clamped["pending_max"])
        repeat(128) { timing.record(it.toLong(), 0, 0) }
        val snapshot = checkNotNull(timing.snapshot())
        assertEquals(JsonPrimitive(128), snapshot["window_samples"])
        assertEquals(JsonPrimitive(129L), snapshot["samples_total"])
        assertEquals(JsonPrimitive(127L), snapshot["queue_wait_ms_max"])
        assertEquals(JsonPrimitive(121L), snapshot["queue_wait_ms_p95"])
        assertEquals(JsonPrimitive(0L), snapshot["processing_ms_max"])
        assertEquals(11, snapshot.size)
        assertFalse(snapshot.keys.any { it in setOf("owner", "sequence", "gesture", "coordinates", "key", "text") })
    }
}
