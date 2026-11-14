import asyncio
import os
import time
from collections import namedtuple

from backend.core import lifespan_registry
from backend.monitoring.device_log_resources import DeviceLogResources
from backend.services import device_log_maintenance
from backend.services.device_log_storage import SWEEP_MARKER


def _samples(collector):
    return {sample.name: sample.value for metric in collector.collect() for sample in metric.samples}


def test_filesystem_collector_measures_the_configured_path(tmp_path, monkeypatch):
    def read_usage(path):
        assert path == tmp_path
        return namedtuple("Usage", "total used free")(100, 90, 10)

    monkeypatch.setattr("backend.monitoring.device_log_resources.shutil.disk_usage", read_usage)
    assert _samples(DeviceLogResources(tmp_path)) == {
        "sphere_device_log_filesystem_available": 1,
        "sphere_device_log_filesystem_free_bytes": 10,
        "sphere_device_log_filesystem_total_bytes": 100,
    }
    assert _samples(DeviceLogResources(tmp_path / "missing")) == {"sphere_device_log_filesystem_available": 0}

    marker = tmp_path / SWEEP_MARKER
    marker.touch()
    os.utime(marker, (100, 100))
    assert _samples(DeviceLogResources(tmp_path))["sphere_device_log_retention_last_success_timestamp_seconds"] == 100


async def test_idle_maintenance_lifecycle_expires_old_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(device_log_maintenance, "DEVICE_LOG_ROOT", tmp_path)
    monkeypatch.setattr(device_log_maintenance, "MAINTENANCE_INTERVAL_SECONDS", 0.01)
    journal = tmp_path / ("a" * 32) / "agent_2000-01-01.log"
    journal.parent.mkdir()
    journal.write_bytes(b"old")
    stale = time.time() - 31 * 86400
    os.utime(journal, (stale, stale))
    assert ("device_log_maintenance", device_log_maintenance._start) in lifespan_registry._startup_hooks
    assert ("device_log_maintenance", device_log_maintenance._stop) in lifespan_registry._shutdown_hooks

    await device_log_maintenance._start()
    task = device_log_maintenance._task
    try:
        await device_log_maintenance._start()
        assert device_log_maintenance._task is task
        async with asyncio.timeout(5):
            while journal.exists():
                await asyncio.sleep(0.01)
    finally:
        await device_log_maintenance._stop()
    assert task is not None and task.done() and device_log_maintenance._task is None
