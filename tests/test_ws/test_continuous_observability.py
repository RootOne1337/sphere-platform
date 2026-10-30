from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry, Histogram

from backend.websocket import continuous_observability as observed


@pytest.fixture
def metric(monkeypatch):
    metric = Mock()
    monkeypatch.setattr(observed, "continuous_stage_duration_seconds", metric)
    return metric


@pytest.mark.asyncio
async def test_returned_unknown_value_is_preserved_and_is_not_labelled_delivery(metric, monkeypatch):
    times = iter([20.0, 20.25])
    monkeypatch.setattr(observed, "_clock", lambda: next(times))
    unknown = object()

    @observed.timed_stage("agent_delivery")
    async def deliver(*, command):
        assert command is unknown
        return unknown

    assert await deliver(command=unknown) is unknown
    assert deliver.__name__ == "deliver"
    metric.labels.assert_called_once_with(stage="agent_delivery", outcome="returned")
    metric.labels.return_value.observe.assert_called_once_with(0.25)


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_metric", [False, True])
async def test_original_failure_survives_observation(metric, broken_metric):
    failure = RuntimeError("private command data must not be a label")
    if broken_metric:
        metric.labels.side_effect = RuntimeError("metric unavailable")

    @observed.timed_stage("redis_lease_operation")
    async def operation():
        raise failure

    with pytest.raises(RuntimeError) as caught:
        await operation()
    assert caught.value is failure
    metric.labels.assert_called_once_with(stage="redis_lease_operation", outcome="raised")


@pytest.mark.asyncio
async def test_cancellation_is_not_consumed_and_native_cleanup_still_runs(metric):
    entered = asyncio.Event()
    released = asyncio.Event()

    @observed.timed_stage("viewer_socket_send")
    async def send():
        try:
            entered.set()
            await asyncio.Future()
        finally:
            released.set()

    task = asyncio.create_task(send())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    metric.labels.assert_called_once_with(stage="viewer_socket_send", outcome="cancelled")


@pytest.mark.asyncio
async def test_broken_metric_does_not_turn_success_into_input_failure(metric):
    metric.labels.return_value.observe.side_effect = OSError("broken metric storage")

    @observed.timed_stage("viewer_admission")
    async def operation():
        return False

    assert await operation() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("times", [(None, 1), (1, None), (2, 1), (0, float("inf")), (0, float("nan"))])
async def test_unknown_or_invalid_elapsed_time_is_not_fabricated(metric, monkeypatch, times):
    clock = iter(times)
    monkeypatch.setattr(observed, "_clock", lambda: next(clock))

    @observed.timed_stage("pubsub_dispatch")
    async def operation():
        return "unchanged"

    assert await operation() == "unchanged"
    metric.labels.assert_not_called()


@pytest.mark.parametrize("value", [float("inf"), float("nan"), RuntimeError("clock unavailable")])
def test_unavailable_clock_is_unknown_without_throwing(monkeypatch, value):
    clock = Mock(side_effect=value) if isinstance(value, Exception) else Mock(return_value=value)
    # Replace this module's reference, not the event loop's shared time module.
    monkeypatch.setattr(observed, "time", SimpleNamespace(monotonic=clock))
    assert observed._clock() is None


@pytest.mark.parametrize("stage", ["device-private-id", "input:continuous:viewer:secret", ""])
def test_dynamic_or_unknown_stage_cannot_create_a_series(stage):
    with pytest.raises(ValueError, match="Unknown continuous timing stage"):
        observed.timed_stage(stage)


@pytest.mark.asyncio
async def test_many_private_payloads_do_not_expand_metric_cardinality(monkeypatch):
    metric = Histogram("finite_input_stage_seconds", "test only", ["stage", "outcome"],
                       registry=CollectorRegistry())
    monkeypatch.setattr(observed, "continuous_stage_duration_seconds", metric)
    for stage in observed.STAGES:
        @observed.timed_stage(stage)
        async def operation(payload):
            return payload

        for index in range(128):
            payload = {"device": f"device-{index}", "owner": f"secret-{index}", "x": index}
            assert await operation(payload) is payload
    samples = [sample for family in metric.collect() for sample in family.samples]
    pairs = {(sample.labels["stage"], sample.labels["outcome"]) for sample in samples}
    assert pairs == {(stage, "returned") for stage in observed.STAGES}
    assert all(set(sample.labels) <= {"stage", "outcome", "le"} for sample in samples)
    assert all("secret-" not in str(sample) and "device-" not in str(sample) for sample in samples)
