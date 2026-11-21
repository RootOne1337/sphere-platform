# backend/services/vpn/killswitch_service.py  TZ-06 SPLIT-4
from __future__ import annotations

from backend.services.vpn.event_publisher import CommandPublisher


class KillSwitchService:
    """
    Manages Kill Switch on remote devices via WebSocket commands.
    The actual iptables / VpnService logic executes on the Android agent.
    """

    def __init__(self, publisher: CommandPublisher) -> None:
        self.publisher = publisher

    @property
    def supported(self) -> bool:
        # The generic pub/sub boolean (including offline queueing) does not
        # establish compatibility with this legacy VPN command envelope.
        return getattr(self.publisher, "supports_killswitch", False) is True

    async def enable_killswitch(
        self,
        device_id: str,
        vpn_endpoint: str,
        method: str = "vpnservice",
    ) -> bool:
        """Submit an enable envelope; a boolean is not an Android execution receipt."""
        return await self.publisher.send_command_to_device(
            device_id,
            {
                "type": "vpn_killswitch",
                "action": "enable",
                "endpoint": vpn_endpoint,
                "method": method,
            },
        )

    async def disable_killswitch(self, device_id: str) -> bool:
        """Submit a disable envelope; a boolean is not an Android execution receipt."""
        return await self.publisher.send_command_to_device(
            device_id,
            {
                "type": "vpn_killswitch",
                "action": "disable",
            },
        )

    async def bulk_disable(self, device_ids: list[str]) -> dict[str, bool]:
        """Disable Kill Switch on a group of devices."""
        results: dict[str, bool] = {}
        for device_id in device_ids:
            results[device_id] = await self.disable_killswitch(device_id)
        return results

    async def bulk_enable(
        self,
        device_ids: list[str],
        vpn_endpoint: str,
        method: str = "vpnservice",
    ) -> dict[str, bool]:
        """Enable Kill Switch on a group of devices. Idempotent per device."""
        results: dict[str, bool] = {}
        for device_id in device_ids:
            results[device_id] = await self.enable_killswitch(
                device_id, vpn_endpoint, method
            )
        return results
