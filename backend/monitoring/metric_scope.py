"""Bounded Prometheus scopes for the production multiprocess collector.

The public client does not support deleting labels in multiprocess mode.
Device snapshots therefore stay in the Redis diagnostics API; additive stream
counters use a separate fleet namespace without retaining device identifiers.
The single-process development profile keeps its existing metric contract.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from prometheus_client import Counter, Gauge


def multiprocess_enabled() -> bool:
    return "PROMETHEUS_MULTIPROC_DIR" in os.environ or "prometheus_multiproc_dir" in os.environ


class DeviceSnapshot:
    """Disabled Prometheus snapshot; deliberately stores no per-device state."""

    def labels(self, *args: Any, **kwargs: Any) -> DeviceSnapshot:
        return self

    def set(self, value: float) -> None:
        pass

    def remove(self, *args: Any) -> None:
        pass


class FleetMetric:
    """Project an existing device instrumentation call onto a bounded metric."""

    def __init__(self, metric: Counter | Gauge, labelnames: Sequence[str]):
        self.metric = metric
        self.labelnames = tuple(labelnames)

    def labels(self, *args: Any, **kwargs: Any) -> Any:
        if args and kwargs:
            raise ValueError("Use positional or keyword labels, not both")
        if args:
            if len(args) != len(self.labelnames):
                raise ValueError("Incorrect label count")
            labels = dict(zip(self.labelnames, args, strict=True))
        else:
            if set(kwargs) != set(self.labelnames):
                raise ValueError("Incorrect label names")
            labels = kwargs
        bounded = {key: str(value) for key, value in labels.items() if key != "device_id"}
        return self.metric.labels(**bounded) if bounded else self.metric


def device_gauge(name: str, documentation: str, labelnames: Sequence[str]) -> Any:
    if multiprocess_enabled():
        return DeviceSnapshot()
    return Gauge(name, documentation, labelnames)


def _fleet_name(name: str) -> str:
    if not name.startswith("sphere_stream_"):
        raise ValueError("Fleet projection requires a stream metric")
    return name.replace("sphere_stream_", "sphere_fleet_stream_", 1)


def device_counter(name: str, documentation: str, labelnames: Sequence[str]) -> Any:
    if not multiprocess_enabled():
        return Counter(name, documentation, labelnames)
    metric = Counter(
        _fleet_name(name), documentation,
        [label for label in labelnames if label != "device_id"],
    )
    return FleetMetric(metric, labelnames)


def device_additive_gauge(name: str, documentation: str, labelnames: Sequence[str]) -> Any:
    if not multiprocess_enabled():
        return Gauge(name, documentation, labelnames)
    metric = Gauge(
        _fleet_name(name), documentation,
        [label for label in labelnames if label != "device_id"],
        multiprocess_mode="livesum",
    )
    return FleetMetric(metric, labelnames)
