"""Cgroup versions, failure isolation and scrape-time exposition regressions."""
from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from backend.monitoring.container_resources import ContainerResources


def write(root: Path, values: dict[str, str]) -> None:
    for name, value in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="ascii")


def scrape(root: Path) -> dict:
    registry = CollectorRegistry()
    registry.register(ContainerResources(root))
    result = {}
    for family in text_string_to_metric_families(generate_latest(registry).decode()):
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            assert key not in result
            result[key] = sample.value
    return result


def get(body: dict, name: str, version: str = "v1", **labels: str):
    return body.get((name, tuple(sorted({"cgroup": version, **labels}.items()))))


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_versions_preserve_units_and_single_container_scope(tmp_path, version):
    write(tmp_path, {
        "cpuacct/cpuacct.usage": "2500000000", "cpu/cpu.cfs_quota_us": "150000",
        "cpu/cpu.cfs_period_us": "100000", "memory/memory.usage_in_bytes": "1024",
        "memory/memory.limit_in_bytes": "4096",
    } if version == "v1" else {
        "cgroup.controllers": "cpu memory", "cpu.stat": "usage_usec 2500000\nuser_usec 2000000",
        "cpu.max": "150000 100000", "memory.current": "1024", "memory.max": "4096",
    })
    body = scrape(tmp_path)
    assert get(body, "sphere_container_cpu_usage_seconds_total", version) == 2.5
    assert get(body, "sphere_container_cpu_quota_cores", version) == 1.5
    assert get(body, "sphere_container_memory_usage_bytes", version) == 1024
    assert get(body, "sphere_container_memory_limit_bytes", version) == 4096
    assert len(body) == 12
    assert all("pid" not in dict(key[1]) for key in body)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_unlimited_limits_are_omitted_not_zero(tmp_path, version):
    write(tmp_path, {"cpu/cpu.cfs_quota_us": "-1", "cpu/cpu.cfs_period_us": "100000",
        "memory/memory.limit_in_bytes": str(1 << 63)} if version == "v1" else {
        "cgroup.controllers": "cpu memory", "cpu.max": "max 100000", "memory.max": "max"})
    body = scrape(tmp_path)
    assert get(body, "sphere_container_cpu_quota_cores", version) is None
    assert get(body, "sphere_container_memory_limit_bytes", version) is None
    for field in ["cpuQuota", "memoryLimit"]:
        assert get(body, "sphere_container_resource_available", version, resource=field) == 0
        assert get(body, "sphere_container_resource_read_timestamp_seconds", version, resource=field) is None


@pytest.mark.parametrize("bad", ["-1", "NaN", "inf", "1.5", "9" * 4097, str(2**64), "", "\u0661"])
def test_failed_memory_does_not_publish_zero_or_retain_old_value(tmp_path, bad):
    write(tmp_path, {"memory/memory.usage_in_bytes": "1234", "cpuacct/cpuacct.usage": "0"})
    assert get(scrape(tmp_path), "sphere_container_memory_usage_bytes") == 1234
    (tmp_path / "memory/memory.usage_in_bytes").write_text(bad, encoding="utf-8")
    body = scrape(tmp_path)
    assert get(body, "sphere_container_memory_usage_bytes") is None
    assert get(body, "sphere_container_resource_available", resource="memory") == 0
    assert get(body, "sphere_container_cpu_usage_seconds_total") == 0
    assert get(body, "sphere_container_resource_available", resource="cpu") == 1


@pytest.mark.parametrize("text", ["usage_usec 1\nusage_usec 2", "usage_usec -2", "other 2", "usage_usec 1 extra"])
def test_invalid_v2_cpu_does_not_fallback_to_v1(tmp_path, text):
    write(tmp_path, {"cgroup.controllers": "cpu", "cpu.stat": text,
        "cpuacct/cpuacct.usage": "1000000000", "memory.current": "0"})
    body = scrape(tmp_path)
    assert get(body, "sphere_container_cpu_usage_seconds_total", "v2") is None
    assert get(body, "sphere_container_memory_usage_bytes", "v2") == 0


@pytest.mark.parametrize("text", ["0 100000", "100000 0", "-1 100000", "max 0", "max", "1 2 3"])
def test_invalid_quota_omits_limit_without_hiding_cpu(tmp_path, text):
    write(tmp_path, {"cgroup.controllers": "cpu", "cpu.max": text, "cpu.stat": "usage_usec 2000"})
    body = scrape(tmp_path)
    assert get(body, "sphere_container_cpu_quota_cores", "v2") is None
    assert get(body, "sphere_container_cpu_usage_seconds_total", "v2") == 0.002


def test_registry_creation_performs_no_controller_reads(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Registration read")
    monkeypatch.setattr(Path, "open", forbidden)
    registry = CollectorRegistry(auto_describe=True)
    registry.register(ContainerResources(tmp_path))


def test_empty_namespace_has_only_explicit_availability(tmp_path):
    body = scrape(tmp_path)
    assert len(body) == 4
    assert all(value == 0 for value in body.values())


def test_denied_namespace_probe_does_not_break_existing_metrics(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("Controller namespace inaccessible")
    monkeypatch.setattr(Path, "exists", denied)
    body = scrape(tmp_path)
    assert len(body) == 4
    assert all(value == 0 for value in body.values())
    assert all('unknown' in str(key) for key in body)
