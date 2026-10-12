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
    assert value == snapshot()
    assert "private" not in str(value)


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
