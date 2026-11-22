package com.sphereplatform.agent.streaming

/** Small owner-thread profiler: no pixels, per-frame history, timer or thread. */
internal class GpuCaptureTiming(
    private val nowNs: () -> Long = System::nanoTime,
    private val report: (Snapshot) -> Unit,
) {
    data class Stage(val samples: Int, val totalNs: Long, val maxNs: Long) {
        val meanMs: Double get() = if (samples == 0) 0.0 else totalNs / samples / 1_000_000.0
        val maxMs: Double get() = maxNs / 1_000_000.0
    }
    data class Snapshot(val windowMs: Long, val texture: Stage, val draw: Stage, val swap: Stage)
    private class Accumulator {
        var samples = 0; var total = 0L; var max = 0L
        fun add(duration: Long?) {
            if (duration == null || duration < 0 || samples == 1_000_000) return
            val bounded = duration.coerceAtMost(60_000_000_000L)
            samples++; total += bounded; max = maxOf(max, bounded)
        }
        fun snapshot() = Stage(samples, total, max)
    }
    private var started = nowNs()
    private var texture = Accumulator()
    private var draw = Accumulator()
    private var swap = Accumulator()

    fun record(textureNs: Long, drawNs: Long?, swapNs: Long?) {
        texture.add(textureNs); draw.add(drawNs); swap.add(swapNs)
        if (nowNs() - started >= 5_000_000_000L) flush()
    }
    fun flush() {
        val now = nowNs()
        if (texture.samples > 0 || draw.samples > 0 || swap.samples > 0) {
            report(Snapshot(((now - started).coerceAtLeast(0)) / 1_000_000,
                texture.snapshot(), draw.snapshot(), swap.snapshot()))
        }
        started = now
        texture = Accumulator(); draw = Accumulator(); swap = Accumulator()
    }
}
