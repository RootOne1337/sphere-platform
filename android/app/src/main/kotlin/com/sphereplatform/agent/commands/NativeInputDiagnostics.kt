package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Process-local facts only. No samples, owners, coordinates, keys or unbounded event log. */
internal class NativeInputDiagnostics(private val uptime: () -> Long) {
    enum class State { DISABLED, IDLE, OPENING, READY, RETIRING, CLEANUP_UNKNOWN }
    enum class Failure {
        ACTIVE_OWNER, RETIRING_OWNER, CAPTURE_UNAVAILABLE, CAPTURE_CHANGED,
        DIRECT_CHANNEL_UNAVAILABLE, AUTHORIZATION_EXPIRED, TRANSPORT_CHANGED,
        SUPERVISOR_BUSY, CLEANUP_UNKNOWN, NATIVE_STARTUP_FAILED, NATIVE_INPUT_FAILED,
        INPUT_NOT_READY, INPUT_REJECTED, RECEIPT_UNAVAILABLE, SCOPE_INACTIVE,
    }
    enum class Event { OPEN_ATTEMPT, OPEN_REJECTION, STARTUP, STARTUP_FAILURE, INPUT_FAILURE, RELEASE, UNKNOWN_RELEASE }

    private val counts = LongArray(Event.entries.size)
    private var failure: Failure? = null
    private var failureAt = 0L
    private var startupDetail: TouchStartupDetail? = null
    private var startupDetailAt = 0L
    private var releaseReason: TouchEndReason? = null
    private var releaseAt = 0L
    private var inputDetail: String? = null
    private var inputDetailAt = 0L

    @Synchronized
    fun inputFailed(detail: String) {
        inputDetail = when (detail) {
            "touch_ack_timeout", "touch_ack_mismatch", "touch_ack_action_mismatch", "touch_process_exited",
            "touch_ack_eof", "native_expired", "native_rejected", "native_unknown", "touch_cleanup_unknown" -> detail
            else -> "native_adapter_exception"
        }
        inputDetailAt = uptime()
    }

    @Synchronized
    fun released(reason: TouchEndReason) { releaseReason = reason; releaseAt = uptime() }

    @Synchronized
    fun startupFailed(detail: TouchStartupDetail) { startupDetail = detail; startupDetailAt = uptime() }

    @Synchronized
    fun record(event: Event, reason: Failure? = null) {
        counts[event.ordinal] = (counts[event.ordinal] + 1).coerceAtMost(MAX_COUNTER)
        if (reason != null) rememberFailure(reason)
    }

    @Synchronized
    fun failed(reason: Failure) = rememberFailure(reason)

    private fun rememberFailure(reason: Failure) { failure = reason; failureAt = uptime() }

    @Synchronized
    fun snapshot(state: State): JsonObject = buildJsonObject {
        put("schema_version", 1)
        put("scope", "agent_process")
        put("state", state.name.lowercase())
        inputDetail?.let {
            put("last_input_detail", it)
            put("last_input_detail_age_ms", (uptime() - inputDetailAt).coerceIn(0, MAX_AGE_MS))
        }
        releaseReason?.let {
            put("last_release_reason", it.name.lowercase())
            put("last_release_age_ms", (uptime() - releaseAt).coerceIn(0, MAX_AGE_MS))
        }
        startupDetail?.let {
            put("last_startup_detail", it.name.lowercase())
            put("last_startup_detail_age_ms", (uptime() - startupDetailAt).coerceIn(0, MAX_AGE_MS))
        }
        failure?.let {
            put("last_failure", it.name.lowercase())
            put("last_failure_age_ms", (uptime() - failureAt).coerceIn(0, MAX_AGE_MS))
        }
        put("open_attempts_total", counts[Event.OPEN_ATTEMPT.ordinal])
        put("open_rejections_total", counts[Event.OPEN_REJECTION.ordinal])
        put("startups_total", counts[Event.STARTUP.ordinal])
        put("startup_failures_total", counts[Event.STARTUP_FAILURE.ordinal])
        put("input_failures_total", counts[Event.INPUT_FAILURE.ordinal])
        put("releases_total", counts[Event.RELEASE.ordinal])
        put("unknown_releases_total", counts[Event.UNKNOWN_RELEASE.ordinal])
    }

    private companion object {
        const val MAX_COUNTER = 9_007_199_254_740_992L
        const val MAX_AGE_MS = 86_400_000L
    }
}
