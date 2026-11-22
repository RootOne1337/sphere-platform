package com.sphereplatform.agent.commands

import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class NativeInputDiagnosticsTest {
    @Test fun `input failure details are bounded vocabulary and never expose exception contents`() {
        var now = 100L
        val diagnostics = NativeInputDiagnostics { now }
        diagnostics.inputFailed("touch_ack_timeout")
        now += 25
        val snapshot = diagnostics.snapshot(NativeInputDiagnostics.State.RETIRING)
        assertEquals(JsonPrimitive("touch_ack_timeout"), snapshot["last_input_detail"])
        assertEquals(JsonPrimitive(25L), snapshot["last_input_detail_age_ms"])
        diagnostics.inputFailed("private token and keystrokes")
        assertEquals(JsonPrimitive("native_adapter_exception"), diagnostics.snapshot(NativeInputDiagnostics.State.IDLE)["last_input_detail"])
    }
    @Test fun `snapshot keeps historical cause separate from current state`() {
        var now = 100L
        val diagnostics = NativeInputDiagnostics { now }
        diagnostics.record(NativeInputDiagnostics.Event.OPEN_ATTEMPT)
        diagnostics.record(NativeInputDiagnostics.Event.OPEN_REJECTION, NativeInputDiagnostics.Failure.ACTIVE_OWNER)
        now += 250
        diagnostics.record(NativeInputDiagnostics.Event.STARTUP)
        val snapshot = diagnostics.snapshot(NativeInputDiagnostics.State.READY)
        assertEquals(JsonPrimitive("ready"), snapshot["state"])
        assertEquals(JsonPrimitive("active_owner"), snapshot["last_failure"])
        assertEquals(JsonPrimitive(250L), snapshot["last_failure_age_ms"])
        assertEquals(JsonPrimitive(1L), snapshot["open_rejections_total"])
        assertEquals(JsonPrimitive("agent_process"), snapshot["scope"])
    }

    @Test fun `missing failure remains absent and monotonic duration is bounded`() {
        var now = 100L
        val diagnostics = NativeInputDiagnostics { now }
        assertFalse("last_failure" in diagnostics.snapshot(NativeInputDiagnostics.State.IDLE))
        diagnostics.failed(NativeInputDiagnostics.Failure.CLEANUP_UNKNOWN)
        now = 99L
        assertEquals(JsonPrimitive(0L), diagnostics.snapshot(NativeInputDiagnostics.State.CLEANUP_UNKNOWN)["last_failure_age_ms"])
        now = Long.MAX_VALUE
        assertEquals(JsonPrimitive(86_400_000L), diagnostics.snapshot(NativeInputDiagnostics.State.CLEANUP_UNKNOWN)["last_failure_age_ms"])
    }

    @Test fun `startup detail is historical fixed vocabulary with a bounded monotonic age`() {
        var now = 100L
        val diagnostics = NativeInputDiagnostics { now }
        assertFalse("last_startup_detail" in diagnostics.snapshot(NativeInputDiagnostics.State.IDLE))
        diagnostics.startupFailed(TouchStartupDetail.ROOT_ADAPTER_UNAVAILABLE)
        now += 20
        val ready = diagnostics.snapshot(NativeInputDiagnostics.State.READY)
        assertEquals(JsonPrimitive("ready"), ready["state"])
        assertEquals(JsonPrimitive("root_adapter_unavailable"), ready["last_startup_detail"])
        assertEquals(JsonPrimitive(20L), ready["last_startup_detail_age_ms"])
        now = Long.MAX_VALUE
        assertEquals(JsonPrimitive(86_400_000L), diagnostics.snapshot(NativeInputDiagnostics.State.READY)["last_startup_detail_age_ms"])
    }

    @Test fun `release cause is fixed bounded history independent of readiness or failure`() {
        var now = 100L
        val diagnostics = NativeInputDiagnostics { now }
        assertFalse("last_release_reason" in diagnostics.snapshot(NativeInputDiagnostics.State.IDLE))
        diagnostics.released(TouchEndReason.VIEWER_HEARTBEAT_EXPIRED)
        now = 130L
        val ready = diagnostics.snapshot(NativeInputDiagnostics.State.READY)
        assertEquals(JsonPrimitive("viewer_heartbeat_expired"), ready["last_release_reason"])
        assertEquals(JsonPrimitive(30L), ready["last_release_age_ms"])
        assertFalse("last_failure" in ready)
        now = Long.MAX_VALUE
        assertEquals(JsonPrimitive(86_400_000L), diagnostics.snapshot(NativeInputDiagnostics.State.READY)["last_release_age_ms"])
        now = 99L
        assertEquals(JsonPrimitive(0L), diagnostics.snapshot(NativeInputDiagnostics.State.IDLE)["last_release_age_ms"])
    }
}
