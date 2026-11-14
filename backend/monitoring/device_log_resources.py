"""Expose journal filesystem capacity without walking the archive on each scrape."""
from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from backend.services.device_log_storage import DEVICE_LOG_ROOT, SWEEP_MARKER


class DeviceLogResources(Collector):
    def __init__(self, root: Path = DEVICE_LOG_ROOT):
        self.root = root

    def describe(self) -> list[Metric]:
        return []

    def collect(self) -> Iterator[Metric]:
        available = GaugeMetricFamily(
            "sphere_device_log_filesystem_available", "Whether the configured journal filesystem could be measured",
        )
        try:
            if self.root.is_symlink() or not self.root.is_dir():
                raise OSError("Journal directory unavailable")
            usage = shutil.disk_usage(self.root)
        except OSError:
            available.add_metric([], 0)
            yield available
            return

        available.add_metric([], 1)
        yield available
        for name, description, value in (
            ("sphere_device_log_filesystem_free_bytes", "Free bytes on the configured device journal filesystem", usage.free),
            ("sphere_device_log_filesystem_total_bytes", "Total bytes on the configured device journal filesystem", usage.total),
        ):
            family = GaugeMetricFamily(name, description)
            family.add_metric([], value)
            yield family

        marker = self.root / SWEEP_MARKER
        try:
            if marker.is_symlink():
                return
            completed_at = marker.stat().st_mtime
        except OSError:
            return
        last_sweep = GaugeMetricFamily(
            "sphere_device_log_retention_last_success_timestamp_seconds", "Time of the last completed journal retention scan",
        )
        last_sweep.add_metric([], completed_at)
        yield last_sweep
