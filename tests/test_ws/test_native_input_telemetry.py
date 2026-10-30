"""The optional APK snapshot must remain bounded, causal and free of input data."""
import pytest
from pydantic import ValidationError

from backend.schemas.stream_diagnostics import NativeInputTelemetry


def snapshot():
    return dict(schema_version=1, scope="agent_process", state="cleanup_unknown",
                last_failure="cleanup_unknown", last_failure_age_ms=120,
                open_attempts_total=3, open_rejections_total=2, startups_total=1,
                startup_failures_total=0, input_failures_total=0, releases_total=0,
                unknown_releases_total=1)


def test_native_input_snapshot_preserves_cause_and_drops_private_extras():
    value = NativeInputTelemetry.model_validate(snapshot() | {
        "owner": "private-owner", "coordinates": [12, 34], "token": "private-token",
        "samples": [{"gesture": 123}],
    }).model_dump()
    assert value == snapshot() | dict(shared_input_timing=None, last_startup_detail=None, last_startup_detail_age_ms=None,
                                     last_release_reason=None, last_release_age_ms=None,
                                     last_input_detail=None, last_input_detail_age_ms=None,
                                     keyboard_commands_total=None, keyboard_accepted_total=None,
                                     keyboard_refused_total=None, keyboard_unknown_total=None,
                                     last_keyboard_result=None, last_keyboard_result_age_ms=None)
    assert "private" not in str(value)


def test_native_input_failure_retains_bounded_adapter_cause_without_keys_or_exception_contents():
    value = NativeInputTelemetry.model_validate(snapshot() | dict(
        last_input_detail="touch_ack_timeout", last_input_detail_age_ms=30,
    ))
    assert value.last_input_detail == "touch_ack_timeout"
    assert value.last_input_detail_age_ms == 30


@pytest.mark.parametrize("change", [
    dict(last_input_detail="private-key-or-exception", last_input_detail_age_ms=1),
    dict(last_input_detail="touch_ack_timeout"), dict(last_input_detail_age_ms=1),
    dict(last_input_detail="touch_ack_timeout", last_input_detail_age_ms=86_400_001),
])
def test_native_input_details_reject_unsupported_unpaired_or_unbounded_values(change):
    with pytest.raises(ValidationError):
        NativeInputTelemetry.model_validate(snapshot() | change)


@pytest.mark.parametrize("change", [
    {"state": "looks_healthy"}, {"scope": "viewer"}, {"last_failure": "private-command"},
    {"last_failure": None}, {"last_failure_age_ms": None}, {"last_failure_age_ms": 86400001},
    {"open_attempts_total": True}, {"open_attempts_total": "3"},
    {"open_attempts_total": 3.0}, {"open_attempts_total": -1}, {"open_attempts_total": 2**53 + 1},
])
def test_native_input_snapshot_rejects_unbounded_or_ambiguous_values(change):
    with pytest.raises(ValidationError):
        NativeInputTelemetry.model_validate(snapshot() | change)


def test_native_input_without_previous_failure_has_no_invented_failure_age():
    data = snapshot() | dict(state="idle", last_failure=None, last_failure_age_ms=None)
    value = NativeInputTelemetry.model_validate(data)
    assert value.last_failure is None and value.last_failure_age_ms is None


def test_native_startup_detail_is_historical_not_current_state():
    value = NativeInputTelemetry.model_validate(snapshot() | dict(
        state="ready", last_startup_detail="root_geometry", last_startup_detail_age_ms=123,
    ))
    assert value.state == "ready"
    assert value.last_startup_detail == "root_geometry"
    assert value.last_startup_detail_age_ms == 123


@pytest.mark.parametrize("change", [
    dict(last_startup_detail="private-address-or-exception", last_startup_detail_age_ms=1),
    dict(last_startup_detail="root_geometry"), dict(last_startup_detail_age_ms=1),
    dict(last_startup_detail="root_geometry", last_startup_detail_age_ms=-1),
    dict(last_startup_detail="root_geometry", last_startup_detail_age_ms=True),
    dict(last_startup_detail="root_geometry", last_startup_detail_age_ms="1"),
    dict(last_startup_detail="root_geometry", last_startup_detail_age_ms=86_400_001),
])
def test_native_startup_detail_rejects_unknown_unpaired_or_unbounded_values(change):
    with pytest.raises(ValidationError):
        NativeInputTelemetry.model_validate(snapshot() | change)


@pytest.mark.parametrize("reason", [
    "owner_retired", "viewer_closed", "viewer_heartbeat_expired", "pending_input_expired",
    "invalid_input", "queue_overflow", "clock_regression", "authorization_expired",
    "scope_inactive", "transport_changed", "capture_changed", "direct_channel_unavailable",
    "receipt_unavailable", "native_failure", "startup_refused", "cleanup_unknown",
])
def test_native_release_cause_is_retained_after_another_owner_becomes_ready(reason):
    value = NativeInputTelemetry.model_validate(snapshot() | dict(
        state="ready", last_release_reason=reason, last_release_age_ms=500,
    ))
    assert value.state == "ready"
    assert value.last_release_reason == reason
    assert value.last_release_age_ms == 500


@pytest.mark.parametrize("change", [
    dict(last_release_reason="private-owner-or-exception", last_release_age_ms=1),
    dict(last_release_reason="viewer_closed"), dict(last_release_age_ms=1),
    dict(last_release_reason="viewer_closed", last_release_age_ms=-1),
    dict(last_release_reason="viewer_closed", last_release_age_ms=True),
    dict(last_release_reason="viewer_closed", last_release_age_ms="1"),
    dict(last_release_reason="viewer_closed", last_release_age_ms=86_400_001),
])
def test_native_release_cause_rejects_unknown_unpaired_or_unbounded_values(change):
    with pytest.raises(ValidationError):
        NativeInputTelemetry.model_validate(snapshot() | change)


def test_older_apk_without_release_cause_remains_compatible():
    value = NativeInputTelemetry.model_validate(snapshot())
    assert value.last_release_reason is None
    assert value.last_release_age_ms is None
