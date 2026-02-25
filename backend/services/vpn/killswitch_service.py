# backend/services/vpn/killswitch_service.py  TZ-06 SPLIT-4
from __future__ import annotations

from backend.services.vpn.event_publisher import EventPublisher


class KillSwitchService:
    """
    Manages Kill Switch on remote devices via WebSocket commands.
    The actual iptables / VpnService logic executes on the Android agent.
    """

    def __init__(self, publisher: EventPublisher) -> None:
        self.publisher = publisher

    async def enable_killswitch(
        self,
        device_id: str,
        vpn_endpoint: str,
        method: str = "vpnservice",
    ) -> bool:
        """Send enable command to device. Returns True if device received it."""
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
        """Send disable command. Returns True if device received it."""
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
