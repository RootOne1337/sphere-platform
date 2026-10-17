"""The runtime guard catches a bind mount that was not rendered/reloaded."""

import pytest

from scripts import check_pilot_gateway_runtime as guard


def test_stale_generated_config_blocks_upstream_probe(monkeypatch, tmp_path):
    source = tmp_path / "nginx.conf"
    source.write_text("server { listen 8081 default_server; }", encoding="utf-8")
    monkeypatch.setattr(guard, "checked_container", lambda project, service: service)
    calls = []

    def docker(*args):
        calls.append(args)
        if args[1] == "public-gateway":
            return "set $pilot_upstream http://nginx:8081;"
        if args[1] == "nginx":
            return "server { listen 80 default_server; }"
        raise AssertionError("readiness must not be queried with a stale listener")

    monkeypatch.setattr(guard, "docker", docker)
    with pytest.raises(RuntimeError, match="generated config is stale"):
        guard.check("sphere-pilot-20260911", source)
    assert len(calls) == 2


def test_stale_generated_listener_is_detected_before_gateway_reload():
    gateway = "set $pilot_upstream http://nginx:8081;"
    source = "server { listen 8081 default_server; }"
    stale_generated = "server { listen 80 default_server; }"

    port = guard.upstream_port(gateway)
    assert guard.listens_on(source, port)
    assert not guard.listens_on(stale_generated, port)


@pytest.mark.parametrize("config", [
    "set $pilot_upstream http://external.invalid:8081;",
    "set $pilot_upstream http://nginx:$dynamic;",
])
def test_guard_rejects_unbounded_upstream(config):
    with pytest.raises(ValueError):
        guard.upstream_port(config)
