"""Bounded, stateless cgroup reads in the container's own namespace.

Read once per scrape, not once per worker into multiprocess mmap. No host/RSS
fallback: a missing controller is unavailable, never a synthetic zero.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

ROOT = Path("/sys/fs/cgroup")
MAX_FILE_BYTES = 4096


def _text(path: Path) -> str:
    with path.open("r", encoding="ascii") as source:
        text = source.read(MAX_FILE_BYTES + 1)
    if len(text) > MAX_FILE_BYTES:
        raise ValueError("Oversized controller value")
    return text.strip()


def _integer(text: str) -> int:
    if not text.isascii() or not text.isdecimal() or len(text) > 20:
        raise ValueError("Invalid controller value")
    number = int(text)
    if number > 2**64 - 1:
        raise ValueError("Controller overflow")
    return number


def _cpu(root: Path, version: str) -> float:
    if version == "v1":
        return _integer(_text(root / "cpuacct/cpuacct.usage")) / 1_000_000_000
    fields: dict[str, str] = {}
    for line in _text(root / "cpu.stat").splitlines():
        key, value = line.split()
        if key in fields:
            raise ValueError("Duplicate controller field")
        fields[key] = value
    return _integer(fields["usage_usec"]) / 1_000_000


def _quota(root: Path, version: str) -> float | None:
    if version == "v1":
        quota = _text(root / "cpu/cpu.cfs_quota_us")
        period = _text(root / "cpu/cpu.cfs_period_us")
        unlimited = quota == "-1"
    else:
        quota, period = _text(root / "cpu.max").split()
        unlimited = quota == "max"
    period_value = _integer(period)
    if period_value == 0:
        raise ValueError("Zero period")
    if unlimited:
        return None
    quota_value = _integer(quota)
    if quota_value == 0:
        raise ValueError("Zero quota")
    return quota_value / period_value


def _memory(root: Path, version: str) -> int:
    path = "memory.current" if version == "v2" else "memory/memory.usage_in_bytes"
    return _integer(_text(root / path))


def _memory_limit(root: Path, version: str) -> int | None:
    path = "memory.max" if version == "v2" else "memory/memory.limit_in_bytes"
    text = _text(root / path)
    if version == "v2" and text == "max":
        return None
    value = _integer(text)
    if version == "v1" and value >= 1 << 60:
        return None
    if value == 0:
        raise ValueError("Zero memory limit")
    return value


class ContainerResources(Collector):
    """Separate scrape-time registry, independent of the worker mmap registry."""

    def __init__(self, root: Path = ROOT):
        self.root = root

    def describe(self) -> list[Metric]:
        # Registration must not perform I/O before the actual scrape.
        return []

    def collect(self) -> Iterator[Metric]:
        try:
            version = "v2" if (self.root / "cgroup.controllers").exists() else "v1"
        except OSError:
            version = "unknown"
        availability = GaugeMetricFamily("sphere_container_resource_available",
            "Controller value available in this scrape; not application health", labels=["resource", "cgroup"])
        timestamp = GaugeMetricFamily("sphere_container_resource_read_timestamp_seconds",
            "Time of successful controller read in this scrape", labels=["resource", "cgroup"])
        for resource, reader, name, description, counter in [
            ("cpu", _cpu, "sphere_container_cpu_usage_seconds", "Cumulative cgroup CPU seconds, all container processes", True),
            ("cpuQuota", _quota, "sphere_container_cpu_quota_cores", "CPU quota / period; omitted when unlimited or unavailable", False),
            ("memory", _memory, "sphere_container_memory_usage_bytes", "Cgroup charged memory including cache; not worker RSS or host RAM", False),
            ("memoryLimit", _memory_limit, "sphere_container_memory_limit_bytes", "Cgroup memory limit; omitted when unlimited or unavailable", False),
        ]:
            try:
                value = None if version == "unknown" else reader(self.root, version)
            except (OSError, ValueError, KeyError):
                value = None
            availability.add_metric([resource, version], float(value is not None))
            if value is not None:
                family = (CounterMetricFamily if counter else GaugeMetricFamily)(name, description, labels=["cgroup"])
                family.add_metric([version], value)
                timestamp.add_metric([resource, version], time.time())
                yield family
        yield availability
        yield timestamp
