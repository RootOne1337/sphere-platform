import pytest
from pydantic import ValidationError

from backend.schemas.stream_diagnostics import SharedInputTimingTelemetry
from backend.websocket.stream_session_history import ControlActionLatency


def timing():
    return dict(scope="shared_actor", window_samples=3, samples_total=20,
                queue_wait_ms_last=2, queue_wait_ms_p95=180, queue_wait_ms_max=180,
                processing_ms_last=6, processing_ms_p95=25, processing_ms_max=25,
                pending_last=0, pending_max=2)


def test_actor_timing_preserves_burst_scalar_facts_and_drops_input():
    payload = timing() | dict(owner="private-owner", keys=[3], coordinates=[10, 30])
    assert SharedInputTimingTelemetry.model_validate(payload).model_dump() == timing()


@pytest.mark.parametrize("change", [
    dict(window_samples=0), dict(window_samples=129), dict(samples_total=2),
    dict(queue_wait_ms_last=-1), dict(queue_wait_ms_p95=181), dict(processing_ms_p95=26),
    dict(pending_last=3), dict(pending_max=361), dict(queue_wait_ms_max=10_001),
    dict(queue_wait_ms_last=True), dict(processing_ms_last="6"), dict(scope="network"),
])
def test_actor_timing_rejects_unbounded_inconsistent_and_ambiguous_data(change):
    with pytest.raises(ValidationError):
        SharedInputTimingTelemetry.model_validate(timing() | change)


def test_action_rtt_retains_a_valid_peak_without_inventing_network_latency():
    assert ControlActionLatency.model_validate(dict(samples=3, p95_ms=180, max_ms=180)).max_ms == 180


@pytest.mark.parametrize("change", [
    dict(samples=0), dict(samples=129), dict(samples=True), dict(p95_ms=181),
    dict(max_ms=10_001), dict(p95_ms=float("nan")), dict(owner="private-owner"),
])
def test_action_rtt_rejects_invalid_samples_and_private_fields(change):
    with pytest.raises(ValidationError):
        ControlActionLatency.model_validate(dict(samples=3, p95_ms=180, max_ms=180) | change)
