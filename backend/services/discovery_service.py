# backend/services/discovery_service.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-5. ADB network discovery via PC Agent (TZ-08 stub).
from __future__ import annotations

import ipaddress
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.schemas.devices import CreateDeviceRequest
from backend.schemas.discovery import (
    DiscoverRequest,
    DiscoveredDevice,
    DiscoverResponse,
)
from backend.services.device_service import DeviceService


class DiscoveryService:
    """
    Обнаружение ADB устройств через PC Agent.

    TZ-08 stub: `pc_agent_svc.send_command_wait()` возвращает пустой список
    до тех пор пока TZ-08 (PC Agent) не реализован. При merge TZ-08 заменить
    _stub_discover_devices на реальный вызов PC Agent.
    """

    def __init__(self, db: AsyncSession, device_svc: DeviceService) -> None:
        self.db = db
        self.device_svc = device_svc

    async def discover_subnet(
        self,
        request: DiscoverRequest,
        org_id: uuid.UUID,
    ) -> DiscoverResponse:
        start = time.monotonic()

        # TZ-08 stub: in production this calls PC Agent via WebSocket RPC
        raw_devices: list[dict] = await self._stub_discover_devices(request)

        # Map serial → existing device_id for already-registered check
        serials = [f"{d['ip']}:{d['port']}" for d in raw_devices]
        existing_map = await self._get_existing_device_map(serials, org_id)

        registered_count = 0
        result: list[DiscoveredDevice] = []

        for dev in raw_devices:
            serial = f"{dev['ip']}:{dev['port']}"
            already = serial in existing_map
            reg_id: str | None = existing_map.get(serial)

            if not already and request.auto_register:
                new_device = await self.device_svc.create_device(
                    org_id,
                    CreateDeviceRequest(
                        name=f"adb_{serial.replace(':', '_').replace('.', '_')}",
                        serial=serial,
                        type="physical",
                        ip_address=dev["ip"],
                        adb_port=dev["port"],
                        android_version=dev.get("android_version"),
                        device_model=dev.get("model"),
                        workstation_id=request.workstation_id,
                        group_id=request.group_id,
                    ),
                )
                reg_id = str(new_device.id)
                registered_count += 1

            result.append(
                DiscoveredDevice(
                    ip=dev["ip"],
                    port=dev["port"],
                    serial=serial,
                    model=dev.get("model"),
                    android_version=dev.get("android_version"),
                    already_registered=already,
                    registered_id=reg_id,
                )
            )

        net = ipaddress.ip_network(request.subnet, strict=False)
        low_port, high_port = request.port_range[0], request.port_range[1]
        ports_per_host = high_port - low_port + 1

        return DiscoverResponse(
            scanned=net.num_addresses * ports_per_host,
            found=len(result),
            registered=registered_count,
            devices=result,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _get_existing_device_map(
        self, serials: list[str], org_id: uuid.UUID
    ) -> dict[str, str]:
        """Return {serial: device_id} for already-registered devices."""
        if not serials:
            return {}
        stmt = select(Device.id, Device.serial).where(
            Device.org_id == org_id, Device.serial.in_(serials)
        )
        rows = (await self.db.execute(stmt)).all()
        return {row.serial: str(row.id) for row in rows}

    async def _stub_discover_devices(
        self, request: DiscoverRequest
    ) -> list[dict]:
        """
        TZ-08 stub: returns empty list.
        Replace with real PC Agent call when TZ-08 is implemented:

            response = await self.pc_agent_svc.send_command_wait(
                workstation_id=str(request.workstation_id),
                command={
                    "type": "discover_adb",
                    "subnet": request.subnet,
                    "port_range": request.port_range,
                    "timeout_ms": request.timeout_ms,
                },
                timeout=60.0,
            )
            return response.get("devices", [])
        """
        return []
