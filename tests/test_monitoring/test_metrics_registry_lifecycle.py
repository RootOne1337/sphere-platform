"""Only the exited master may remove its own private metrics registry."""
import os
from types import SimpleNamespace

import pytest

from backend import gunicorn_conf


@pytest.fixture
def registry(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    path = root / "master.abcdefgh"
    path.mkdir(mode=0o700)
    (path / ".owner").write_text(str(os.getpid()))
    monkeypatch.setattr(gunicorn_conf, "_REGISTRY_ROOT", root, raising=False)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(path))
    monkeypatch.setenv("SPHERE_METRICS_OWNER_PID", str(os.getpid()))
    return path


def test_exit_removes_owned_registry_and_preserves_adjacent_operator_data(registry):
    sentinel = registry.parent / "operator-data"
    sentinel.mkdir()
    (sentinel / "keep").write_text("operator")
    (registry / "counter_123.db").write_bytes(b"retired-counter")
    gunicorn_conf.on_exit(SimpleNamespace(WORKERS={}))
    assert not registry.exists()
    assert (sentinel / "keep").read_text() == "operator"


@pytest.mark.parametrize("invalid", ["active-worker", "missing-marker", "foreign-marker", "foreign-pid", "outside-root", "root"])
def test_exit_refuses_registry_without_exclusive_ownership(registry, monkeypatch, invalid):
    workers = {}
    if invalid == "active-worker":
        workers = {123: object()}
    elif invalid == "missing-marker":
        (registry / ".owner").unlink()
    elif invalid == "foreign-marker":
        (registry / ".owner").write_text("not-owner")
    elif invalid == "foreign-pid":
        monkeypatch.setenv("SPHERE_METRICS_OWNER_PID", "999999999")
    elif invalid == "outside-root":
        monkeypatch.setattr(gunicorn_conf, "_REGISTRY_ROOT", registry.parent / "different-root")
    elif invalid == "root":
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(registry.parent))
    gunicorn_conf.on_exit(SimpleNamespace(WORKERS=workers))
    assert registry.is_dir()


def test_exit_without_registry_is_noop(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    gunicorn_conf.on_exit(SimpleNamespace(WORKERS={}))
