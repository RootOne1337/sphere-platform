package com.sphereplatform.agent.commands

import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

/** Versioned single-finger DAG action; never a list of independent swipes. */
internal class TimedPointerPath private constructor(val width: Int, val height: Int, val points: List<Point>) {
    data class Point(val atMs: Long, val action: Int, val x: Int, val y: Int)
    val durationMs get() = points.last().atMs

    companion object {
        const val MAX_POINTS = 4096
        const val MAX_DURATION_MS = 60_000L
        const val MAX_BYTES = 256 * 1024

        fun parse(value: JsonObject): TimedPointerPath {
            fun number(v: JsonElement?): Long {
                val p = v as? JsonPrimitive
                require(p != null && !p.isString && p.content.matches(Regex("0|[1-9][0-9]*"))) { "pointer_path_number" }
                return p.longOrNull ?: error("pointer_path_number")
            }
            require(value.keys == setOf("schema_version", "frame_width", "frame_height", "points")) { "pointer_path_fields" }
            require(value.toString().toByteArray(Charsets.UTF_8).size <= MAX_BYTES) { "pointer_path_budget" }
            require(number(value["schema_version"]) == 1L) { "pointer_path_version" }
            val width = number(value["frame_width"]).also { require(it in 1..16384) { "pointer_path_geometry" } }.toInt()
            val height = number(value["frame_height"]).also { require(it in 1..16384) { "pointer_path_geometry" } }.toInt()
            val raw = value["points"] as? JsonArray ?: error("pointer_path_points")
            require(raw.size in 2..MAX_POINTS) { "pointer_path_points" }
            var previous = 0L
            val points = raw.mapIndexed { index, item ->
                val p = item as? JsonObject ?: error("pointer_path_point")
                require(p.keys == setOf("t_ms", "action", "x", "y")) { "pointer_path_point_fields" }
                val at = number(p["t_ms"])
                require(at in previous..MAX_DURATION_MS && (index != 0 || at == 0L)) { "pointer_path_time" }
                previous = at
                val action = number(p["action"])
                val expected = when (index) { 0 -> RootTouchSession.DOWN; raw.lastIndex -> RootTouchSession.UP; else -> RootTouchSession.MOVE }
                require(action == expected.toLong()) { "pointer_path_order" }
                val x = number(p["x"]); val y = number(p["y"])
                require(x < width && y < height) { "pointer_path_bounds" }
                Point(at, expected, x.toInt(), y.toInt())
            }
            return TimedPointerPath(width, height, points)
        }
    }
}

/** Partial input must never enter an ordinary node retry. Integration must preserve this discriminator. */
internal class PointerPathInterruptedException(val attemptedPoints: Int, reason: String) :
    RootCommandOutcomeUnknownException("$reason; attempted_points=$attemptedPoints")

/** One absolute local schedule; holds keep one native finger, not a sequence of discrete swipes.
 * Caller must hold device input authority and drain prior root commands before factory.open.
 */
internal class TimedPointerPathPlayer(
    private val factory: TouchPipeFactory,
    private val uptime: () -> Long,
    private val wait: suspend (Long) -> Unit = { delay(it) },
    private val onCleanupUnknown: () -> Unit,
) {
    data class Result(val points: Int, val durationMs: Long, val maxScheduleLatenessMs: Long)

    suspend fun play(path: TimedPointerPath, binding: TouchBinding, current: () -> Boolean,
                     checkpoint: suspend () -> Unit = {}): Result {
        require(path.points.size in 2..TimedPointerPath.MAX_POINTS)
        require((path.width > path.height) == (binding.width > binding.height)) { "pointer_path_orientation" }
        checkpoint(); check(current()) { "pointer_path_capture_changed" }
        val pipe = try { factory.open(binding) } catch (failure: TouchPipeCleanupUnknownException) {
            onCleanupUnknown(); throw PointerPathInterruptedException(0, "pointer_path_startup_cleanup_unknown")
        }
        var attempted = 0
        try {
            val start = uptime()
            var lastClock = start
            var lastActivity = start
            var sequence = 0
            var held = false
            var x = 0; var y = 0
            var maxLateness = 0L
            for (point in path.points) {
                while (true) {
                    currentCoroutineContext().ensureActive(); checkpoint()
                    if (!current()) throw PointerPathInterruptedException(attempted, "pointer_path_capture_changed")
                    val now = uptime()
                    if (now < lastClock) throw PointerPathInterruptedException(attempted, "pointer_path_clock_regression")
                    lastClock = now
                    val remaining = start + point.atMs - now
                    if (remaining <= 0) break
                    if (now - lastActivity >= 250) {
                        val ack = pipe.send(TouchSample(++sequence, if (held) 1 else 0, RootTouchSession.HEARTBEAT, x, y, now))
                        if (ack.sequence != sequence || ack.status != 2) throw PointerPathInterruptedException(attempted, "pointer_path_heartbeat_unknown")
                        lastActivity = uptime()
                    }
                    wait(minOf(remaining, 50))
                }
                val now = uptime()
                val late = now - start - point.atMs
                // Refuse stale catch-up bursts. Never convert lag into a rapid series of old inputs.
                if (late > 100) throw PointerPathInterruptedException(attempted, "pointer_path_schedule_missed")
                maxLateness = maxOf(maxLateness, late)
                x = (point.x.toLong() * binding.width / path.width).toInt().coerceIn(0, binding.width - 1)
                y = (point.y.toLong() * binding.height / path.height).toInt().coerceIn(0, binding.height - 1)
                attempted++ // Even a throwing/partial write may have submitted this point.
                val ack = pipe.send(TouchSample(++sequence, 1, point.action, x, y, now))
                if (ack.sequence != sequence || ack.status != 1) throw PointerPathInterruptedException(attempted, "pointer_path_point_unknown")
                held = point.action != RootTouchSession.UP
                lastActivity = uptime()
            }
            return Result(attempted, path.durationMs, maxLateness)
        } catch (failure: Exception) {
            if (failure is kotlinx.coroutines.CancellationException || failure is RootCommandOutcomeUnknownException) throw failure
            // An IOException may follow a partial native write. It cannot enter node retry/on_failure.
            if (attempted != 0) throw PointerPathInterruptedException(attempted, "pointer_path_interrupted")
            throw failure
        } finally {
            val confirmed = withContext(NonCancellable) { runCatching { pipe.closeAndConfirm() }.getOrDefault(false) }
            if (!confirmed) { onCleanupUnknown(); throw PointerPathInterruptedException(attempted, "pointer_path_cleanup_unknown") }
        }
    }
}
