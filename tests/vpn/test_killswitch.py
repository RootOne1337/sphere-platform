# tests/vpn/test_killswitch.py  TZ-06 SPLIT-4
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.vpn.event_publisher import EventPublisher
from backend.services.vpn.killswitch_service import KillSwitchService


def _make_ks(return_value: bool = True) -> KillSwitchService:
    publisher = EventPublisher()
    publisher.send_command_to_device = AsyncMock(return_value=return_value)
    return KillSwitchService(publisher)


class TestKillSwitchService:

    @pytest.mark.asyncio
    async def test_enable_sends_correct_command(self):
        ks = _make_ks(return_value=True)
        result = await ks.enable_killswitch("device:5555", "vpn.example.com:51820")

        assert result is True
        ks.publisher.send_command_to_device.assert_called_once()
        _, cmd = ks.publisher.send_command_to_device.call_args[0]
        assert cmd["type"] == "vpn_killswitch"
        assert cmd["action"] == "enable"
        assert cmd["endpoint"] == "vpn.example.com:51820"
        assert cmd["method"] == "vpnservice"

    @pytest.mark.asyncio
    async def test_enable_with_iptables_method(self):
        ks = _make_ks()
        await ks.enable_killswitch("device:5555", "vpn.example.com:51820", method="iptables")

        _, cmd = ks.publisher.send_command_to_device.call_args[0]
        assert cmd["method"] == "iptables"

    @pytest.mark.asyncio
    async def test_disable_sends_correct_command(self):
        ks = _make_ks(return_value=True)
        result = await ks.disable_killswitch("device:5555")

        assert result is True
        _, cmd = ks.publisher.send_command_to_device.call_args[0]
        assert cmd["type"] == "vpn_killswitch"
        assert cmd["action"] == "disable"

    @pytest.mark.asyncio
    async def test_enable_returns_false_when_device_offline(self):
        ks = _make_ks(return_value=False)
        result = await ks.enable_killswitch("device:5555", "vpn.example.com:51820")
        assert result is False

    @pytest.mark.asyncio
    async def test_bulk_enable_all_devices(self):
        ks = _make_ks(return_value=True)
        device_ids = ["d1", "d2", "d3"]
        results = await ks.bulk_enable(device_ids, "vpn.example.com:51820")

        assert set(results.keys()) == set(device_ids)
        assert all(v is True for v in results.values())
        assert ks.publisher.send_command_to_device.call_count == 3

    @pytest.mark.asyncio
    async def test_bulk_enable_mixed_results(self):
        """Some devices online, some offline."""
        publisher = EventPublisher()
        call_count = 0

        async def mock_send(device_id, cmd):
            nonlocal call_count
            call_count += 1
            # First device offline, rest online
            return call_count > 1

        publisher.send_command_to_device = mock_send
        ks = KillSwitchService(publisher)

        results = await ks.bulk_enable(["d1", "d2", "d3"], "vpn.example.com:51820")

        assert results["d1"] is False
        assert results["d2"] is True
        assert results["d3"] is True

    @pytest.mark.asyncio
    async def test_enable_idempotent(self):
        """Calling enable twice sends two commands (device handles dedup)."""
        ks = _make_ks()
        await ks.enable_killswitch("device:5555", "vpn.example.com:51820")
        await ks.enable_killswitch("device:5555", "vpn.example.com:51820")
        assert ks.publisher.send_command_to_device.call_count == 2

    @pytest.mark.asyncio
    async def test_bulk_enable_empty_list(self):
        ks = _make_ks()
        results = await ks.bulk_enable([], "vpn.example.com:51820")
        assert results == {}
        ks.publisher.send_command_to_device.assert_not_called()
