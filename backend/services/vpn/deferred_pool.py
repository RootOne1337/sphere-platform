"""Initialize provider credentials only after route validation/authorization."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from backend.services.vpn.pool_service import VPNAssignment, VPNPoolService


class DeferredVPNPoolService:
    def __init__(self, factory: Callable[[], VPNPoolService]) -> None:
        self.factory = factory
        self.service: VPNPoolService | None = None

    def _get(self) -> VPNPoolService:
        if self.service is None:
            self.service = self.factory()
        return self.service

    async def assign_vpn(self, device_id: str, org_id: uuid.UUID, split_tunnel: bool = True) -> VPNAssignment:
        return await self._get().assign_vpn(device_id, org_id, split_tunnel)

    async def revoke_vpn(self, device_id: str, org_id: uuid.UUID) -> None:
        await self._get().revoke_vpn(device_id, org_id)

    async def close(self) -> None:
        if self.service is not None:
            await self.service.close()
