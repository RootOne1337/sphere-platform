# backend/services/discovery_service.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-5. ADB network discovery via PC Agent (TZ-08).
from __future__ import annotations

import asyncio
import ipaddress
import time
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.schemas.devices import CreateDeviceRequest
from backend.schemas.discovery import (
    DiscoveredDevice,
    DiscoverRequest,
    DiscoverResponse,
)
from backend.services.device_service import DeviceService
from backend.websocket.pubsub_router import get_pubsub_router

logger = structlog.get_logger()


class DiscoveryService:
    """
    Обнаружение ADB устройств через PC Agent.

    Отправляет команду `discover_adb` на указанную воркстанцию через
    WebSocket RPC (PubSubRouter.send_command_wait_result) и получает
    список найденных устройств.
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

        # Call PC Agent for ADB device discovery via WebSocket RPC
        raw_devices: list[dict] = await self._discover_devices_via_agent(request)

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

    async def _discover_devices_via_agent(
        self, request: DiscoverRequest
    ) -> list[dict]:
        """
        Send discover_adb command to PC Agent via WebSocket RPC.
        Falls back to empty list if agent is offline or no PubSubRouter.
        """
        pubsub = get_pubsub_router()
        if pubsub is None:
            logger.warning("PubSubRouter not initialized, skipping discovery")
            return []

        workstation_id = str(request.workstation_id) if request.workstation_id else None
        if not workstation_id:
            logger.warning("No workstation_id provided for discovery")
            return []

        command = {
            "type": "discover_adb",
            "subnet": request.subnet,
            "port_range": list(request.port_range),
            "timeout_ms": request.timeout_ms,
        }

        try:
            response = await pubsub.send_command_wait_result(
                device_id=workstation_id,
                command=command,
                timeout=max(60.0, (request.timeout_ms or 30000) / 1000 + 10),
            )
            devices = response.get("devices", [])
            logger.info(
                "Discovery completed via PC Agent",
                workstation_id=workstation_id,
                found=len(devices),
            )
            return devices
        except asyncio.TimeoutError:
            logger.warning(
                "Discovery timeout from PC Agent",
                workstation_id=workstation_id,
            )
            return []
        except Exception as exc:
            logger.warning(
                "Discovery via PC Agent failed",
                workstation_id=workstation_id,
                error=str(exc),
            )
            return []
