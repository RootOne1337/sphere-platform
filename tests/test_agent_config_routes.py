"""Generated fleet configs must retain the optional second management route."""
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("fallback", [None, "https://secondary.invalid"])
def test_config_generator_preserves_optional_fallback(fallback):
    path = Path(__file__).resolve().parents[1] / "agent-config/scripts/generate_device_config.py"
    spec = importlib.util.spec_from_file_location("route_config_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = {"config_version": 1, "server_url": "https://primary.invalid", "enrollment_api_key": "sphr_isolated"}
    if fallback is not None:
        env["fallback_server_url"] = fallback
    config = module.generate_single_config(env, workstation_id="isolated", instance_index=1)
    assert config.get("fallback_server_url") == fallback
    assert config["server_url"] == env["server_url"]
